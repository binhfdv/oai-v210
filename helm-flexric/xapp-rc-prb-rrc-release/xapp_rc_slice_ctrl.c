/*
 * Licensed to the OpenAirInterface (OAI) Software Alliance under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The OpenAirInterface Software Alliance licenses this file to You under
 * the OAI Public License, Version 1.1  (the "License"); you may not use this
 * file except in compliance with the License.  You may obtain a copy of the
 * License at
 *
 *      http://www.openairinterface.org/?page_id=698
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include "../../../../src/xApp/e42_xapp_api.h"
#include "../../../../src/util/ngran_types.h"
#include "../../../../src/util/time_now_us.h"
#include "../../../../src/util/alg_ds/ds/lock_guard/lock_guard.h"
#include "../../../../src/sm/rc_sm/rc_sm_id.h"
#include "../../../../src/sm/rc_sm/ie/rc_data_ie.h"
#include "../../../../src/sm/rc_sm/ie/ir/ran_param_struct.h"
#include "../../../../src/sm/rc_sm/ie/ir/ran_param_list.h"
#include "../../../../src/util/byte_array.h"
#include <stdlib.h>
#include <stdio.h>
#include <time.h>
#include <unistd.h>
#include <arpa/inet.h>
#include <pthread.h>
#include <sys/socket.h>
#include <string.h>
#include <limits.h>


#define PORT 8080
#define MAX_CLIENTS 2
#define BUFFER_SIZE 2000

char g_atd_server_ip[64] = {0};
char g_gnb_telnet_ip[64] = {0};

static void load_atd_server_ip(fr_args_t const* args)
{
    char* line = NULL;
    size_t len = 0;
    ssize_t read;

    FILE* fp = fopen(args->conf_file, "r");
    if (fp == NULL) {
        printf("%s not found\n", args->conf_file);
        exit(EXIT_FAILURE);
    }

    while ((read = getline(&line, &len, fp)) != -1) {
        const char* needles[2] = { "ATD_SERVER_IP =", "GNB_TELNET_IP =" };
        char* dsts[2] = { g_atd_server_ip, g_gnb_telnet_ip };
        size_t dstsz[2] = { sizeof(g_atd_server_ip), sizeof(g_gnb_telnet_ip) };
        for (int k = 0; k < 2; k++) {
            char* ans = strstr(line, needles[k]);
            if (ans != NULL) {
                ans += strlen(needles[k]);
                while (*ans == ' ') ans++;
                char* end = ans + strlen(ans) - 1;
                while (end > ans && (*end == '\n' || *end == '\r' || *end == ' ')) end--;
                *(end + 1) = '\0';
                strncpy(dsts[k], ans, dstsz[k] - 1);
            }
        }
    }
    free(line);
    fclose(fp);
}

typedef struct {
    int socket;
    int client_id;
} client_data_t;

typedef struct {
    int sst;
    int sd;
    int normal_count;
    int anomaly_count;
    int prb_ratio;       /* percentage 0-100 */
    int prev_prb_ratio;
    int rrc_ue_id;
    bool updated;        /* set when fresh data arrives this cycle */
} ue_data_t;


ue_data_t ue_data[MAX_CLIENTS];
int client_sockets[MAX_CLIENTS];
int clients_connected = 0;

pthread_mutex_t lock;
pthread_cond_t cond;


/* RAN Parameter IDs (Table 8.4.3.6, O-RAN E2SM-RC) */
typedef enum {
  RRM_Policy_Ratio_List_8_4_3_6        = 1,
  RRM_Policy_Ratio_Group_8_4_3_6       = 2,
  RRM_Policy_8_4_3_6                   = 3,
  RRM_Policy_Member_List_8_4_3_6       = 4,
  RRM_Policy_Member_8_4_3_6            = 5,
  PLMN_Identity_8_4_3_6               = 6,
  S_NSSAI_8_4_3_6                     = 7,
  SST_8_4_3_6                         = 8,
  SD_8_4_3_6                          = 9,
  Min_PRB_Policy_Ratio_8_4_3_6        = 10,
  Max_PRB_Policy_Ratio_8_4_3_6        = 11,
  Dedicated_PRB_Policy_Ratio_8_4_3_6  = 12,
} slice_level_prb_quota_param_id_e;

/* Build one RRM_Policy_Ratio_Group list entry for the given slice */
static void gen_rrm_policy_ratio_group(lst_ran_param_t* grp,
                                       const char* sst_str,
                                       const char* sd_str,
                                       int min_ratio,
                                       int dedicated_ratio,
                                       int max_ratio)
{
  grp->ran_param_struct.sz_ran_param_struct = 4;
  grp->ran_param_struct.ran_param_struct = calloc(4, sizeof(seq_ran_param_t));
  assert(grp->ran_param_struct.ran_param_struct != NULL && "Memory exhausted");

  /* p[0] = RRM_Policy (STRUCTURE) */
  seq_ran_param_t* RRM_Policy = &grp->ran_param_struct.ran_param_struct[0];
  RRM_Policy->ran_param_id = RRM_Policy_8_4_3_6;
  RRM_Policy->ran_param_val.type = STRUCTURE_RAN_PARAMETER_VAL_TYPE;
  RRM_Policy->ran_param_val.strct = calloc(1, sizeof(ran_param_struct_t));
  assert(RRM_Policy->ran_param_val.strct != NULL && "Memory exhausted");
  RRM_Policy->ran_param_val.strct->sz_ran_param_struct = 1;
  RRM_Policy->ran_param_val.strct->ran_param_struct = calloc(1, sizeof(seq_ran_param_t));
  assert(RRM_Policy->ran_param_val.strct->ran_param_struct != NULL && "Memory exhausted");

  /* RRM_Policy_Member_List (LIST) */
  seq_ran_param_t* Member_List = &RRM_Policy->ran_param_val.strct->ran_param_struct[0];
  Member_List->ran_param_id = RRM_Policy_Member_List_8_4_3_6;
  Member_List->ran_param_val.type = LIST_RAN_PARAMETER_VAL_TYPE;
  Member_List->ran_param_val.lst = calloc(1, sizeof(ran_param_list_t));
  assert(Member_List->ran_param_val.lst != NULL && "Memory exhausted");
  Member_List->ran_param_val.lst->sz_lst_ran_param = 1;
  Member_List->ran_param_val.lst->lst_ran_param = calloc(1, sizeof(lst_ran_param_t));
  assert(Member_List->ran_param_val.lst->lst_ran_param != NULL && "Memory exhausted");

  /* RRM_Policy_Member (STRUCTURE: PLMN_Identity + S-NSSAI) */
  lst_ran_param_t* Member = &Member_List->ran_param_val.lst->lst_ran_param[0];
  Member->ran_param_struct.sz_ran_param_struct = 2;
  Member->ran_param_struct.ran_param_struct = calloc(2, sizeof(seq_ran_param_t));
  assert(Member->ran_param_struct.ran_param_struct != NULL && "Memory exhausted");

  /* PLMN_Identity */
  seq_ran_param_t* PLMN = &Member->ran_param_struct.ran_param_struct[0];
  PLMN->ran_param_id = PLMN_Identity_8_4_3_6;
  PLMN->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  PLMN->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(PLMN->ran_param_val.flag_false != NULL && "Memory exhausted");
  PLMN->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;
  byte_array_t plmn = cp_str_to_ba("00101");
  PLMN->ran_param_val.flag_false->octet_str_ran.len = plmn.len;
  PLMN->ran_param_val.flag_false->octet_str_ran.buf = plmn.buf;

  /* S-NSSAI (STRUCTURE: SST + SD) */
  seq_ran_param_t* S_NSSAI = &Member->ran_param_struct.ran_param_struct[1];
  S_NSSAI->ran_param_id = S_NSSAI_8_4_3_6;
  S_NSSAI->ran_param_val.type = STRUCTURE_RAN_PARAMETER_VAL_TYPE;
  S_NSSAI->ran_param_val.strct = calloc(1, sizeof(ran_param_struct_t));
  assert(S_NSSAI->ran_param_val.strct != NULL && "Memory exhausted");
  S_NSSAI->ran_param_val.strct->sz_ran_param_struct = 2;
  S_NSSAI->ran_param_val.strct->ran_param_struct = calloc(2, sizeof(seq_ran_param_t));
  assert(S_NSSAI->ran_param_val.strct->ran_param_struct != NULL && "Memory exhausted");

  seq_ran_param_t* SST = &S_NSSAI->ran_param_val.strct->ran_param_struct[0];
  SST->ran_param_id = SST_8_4_3_6;
  SST->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  SST->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(SST->ran_param_val.flag_false != NULL && "Memory exhausted");
  SST->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;
  byte_array_t sst_ba = cp_str_to_ba(sst_str);
  SST->ran_param_val.flag_false->octet_str_ran.len = sst_ba.len;
  SST->ran_param_val.flag_false->octet_str_ran.buf = sst_ba.buf;

  seq_ran_param_t* SD = &S_NSSAI->ran_param_val.strct->ran_param_struct[1];
  SD->ran_param_id = SD_8_4_3_6;
  SD->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  SD->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(SD->ran_param_val.flag_false != NULL && "Memory exhausted");
  SD->ran_param_val.flag_false->type = OCTET_STRING_RAN_PARAMETER_VALUE;
  byte_array_t sd_ba = cp_str_to_ba(sd_str);
  SD->ran_param_val.flag_false->octet_str_ran.len = sd_ba.len;
  SD->ran_param_val.flag_false->octet_str_ran.buf = sd_ba.buf;

  /* p[1] = Min_PRB_Policy_Ratio (INTEGER) */
  seq_ran_param_t* Min_PRB = &grp->ran_param_struct.ran_param_struct[1];
  Min_PRB->ran_param_id = Min_PRB_Policy_Ratio_8_4_3_6;
  Min_PRB->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  Min_PRB->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(Min_PRB->ran_param_val.flag_false != NULL && "Memory exhausted");
  Min_PRB->ran_param_val.flag_false->type = INTEGER_RAN_PARAMETER_VALUE;
  Min_PRB->ran_param_val.flag_false->int_ran = min_ratio;

  /* p[2] = Max_PRB_Policy_Ratio (INTEGER) */
  seq_ran_param_t* Max_PRB = &grp->ran_param_struct.ran_param_struct[2];
  Max_PRB->ran_param_id = Max_PRB_Policy_Ratio_8_4_3_6;
  Max_PRB->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  Max_PRB->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(Max_PRB->ran_param_val.flag_false != NULL && "Memory exhausted");
  Max_PRB->ran_param_val.flag_false->type = INTEGER_RAN_PARAMETER_VALUE;
  Max_PRB->ran_param_val.flag_false->int_ran = max_ratio;

  /* p[3] = Dedicated_PRB_Policy_Ratio (INTEGER) */
  seq_ran_param_t* Ded_PRB = &grp->ran_param_struct.ran_param_struct[3];
  Ded_PRB->ran_param_id = Dedicated_PRB_Policy_Ratio_8_4_3_6;
  Ded_PRB->ran_param_val.type = ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE;
  Ded_PRB->ran_param_val.flag_false = calloc(1, sizeof(ran_parameter_value_t));
  assert(Ded_PRB->ran_param_val.flag_false != NULL && "Memory exhausted");
  Ded_PRB->ran_param_val.flag_false->type = INTEGER_RAN_PARAMETER_VALUE;
  Ded_PRB->ran_param_val.flag_false->int_ran = dedicated_ratio;
}

/* Send RC SM Style 2 Action 6 (Slice-level PRB quota) to all DU nodes */
void enforce_prb_ratio(e2_node_arr_xapp_t nodes)
{
  /* Build sst/sd strings from ue_data */
  char sst_str[MAX_CLIENTS][8];
  char sd_str[MAX_CLIENTS][16];
  for (int i = 0; i < MAX_CLIENTS; i++) {
    snprintf(sst_str[i], sizeof(sst_str[i]), "%d", ue_data[i].sst);
    snprintf(sd_str[i],  sizeof(sd_str[i]),  "%d", ue_data[i].sd);
  }

  printf("[xApp]: PRB ratio: slice0(sst=%d sd=%d)=%d%%, slice1(sst=%d sd=%d)=%d%%\n",
         ue_data[0].sst, ue_data[0].sd, ue_data[0].prb_ratio,
         ue_data[1].sst, ue_data[1].sd, ue_data[1].prb_ratio);

  /* Build RC SM Control message */
  rc_ctrl_req_data_t rc_ctrl = {0};

  /* Header: Style 2, Action 6 */
  rc_ctrl.hdr.format = FORMAT_1_E2SM_RC_CTRL_HDR;
  rc_ctrl.hdr.frmt_1.ric_style_type = 2;
  rc_ctrl.hdr.frmt_1.ctrl_act_id = 6;
  /* UE ID: dummy GNB UE ID (slice-level control, not per-UE) */
  rc_ctrl.hdr.frmt_1.ue_id.type = GNB_UE_ID_E2SM;
  rc_ctrl.hdr.frmt_1.ue_id.gnb.amf_ue_ngap_id = 0;
  rc_ctrl.hdr.frmt_1.ue_id.gnb.guami.plmn_id.mcc = 1;
  rc_ctrl.hdr.frmt_1.ue_id.gnb.guami.plmn_id.mnc = 1;
  rc_ctrl.hdr.frmt_1.ue_id.gnb.guami.plmn_id.mnc_digit_len = 2;

  /* Message: Format 1 with RRM_Policy_Ratio_List */
  rc_ctrl.msg.format = FORMAT_1_E2SM_RC_CTRL_MSG;
  rc_ctrl.msg.frmt_1.sz_ran_param = 1;
  rc_ctrl.msg.frmt_1.ran_param = calloc(1, sizeof(seq_ran_param_t));
  assert(rc_ctrl.msg.frmt_1.ran_param != NULL && "Memory exhausted");

  /* RRM_Policy_Ratio_List (LIST of MAX_CLIENTS groups) */
  seq_ran_param_t* ratio_list = &rc_ctrl.msg.frmt_1.ran_param[0];
  ratio_list->ran_param_id = RRM_Policy_Ratio_List_8_4_3_6;
  ratio_list->ran_param_val.type = LIST_RAN_PARAMETER_VAL_TYPE;
  ratio_list->ran_param_val.lst = calloc(1, sizeof(ran_param_list_t));
  assert(ratio_list->ran_param_val.lst != NULL && "Memory exhausted");
  ratio_list->ran_param_val.lst->sz_lst_ran_param = MAX_CLIENTS;
  ratio_list->ran_param_val.lst->lst_ran_param = calloc(MAX_CLIENTS, sizeof(lst_ran_param_t));
  assert(ratio_list->ran_param_val.lst->lst_ran_param != NULL && "Memory exhausted");

  for (int i = 0; i < MAX_CLIENTS; i++) {
    gen_rrm_policy_ratio_group(
      &ratio_list->ran_param_val.lst->lst_ran_param[i],
      sst_str[i], sd_str[i],
      1,                        /* min_ratio: 1% floor */
      ue_data[i].prb_ratio,    /* dedicated ratio from anomaly detection */
      100                       /* max_ratio: 100% ceiling */
    );
  }

  /* Send to DU and monolithic gNB nodes */
  for (size_t i = 0; i < nodes.len; ++i) {
    if (NODE_IS_DU(nodes.n[i].id.type) || NODE_IS_MONOLITHIC(nodes.n[i].id.type)) {
      control_sm_xapp_api(&nodes.n[i].id, SM_RC_ID, &rc_ctrl);
    }
  }

  free_rc_ctrl_req_data(&rc_ctrl);
}


void *client_handler(void *client_data) {
    client_data_t *data = (client_data_t*)client_data;
    int sock = data->socket;
    int client_id = data->client_id;
    int read_size;
    char client_message[BUFFER_SIZE];

    while ((read_size = recv(sock, client_message, BUFFER_SIZE, 0)) > 0) {
        client_message[read_size] = '\0';

        printf("Received message from client %d: %s\n", client_id + 1, client_message);

        int sst, sd, normal_count, anomaly_count;
        if (sscanf(client_message, "sst:%d,sd:%d,normal:%d,anomaly:%d",
                   &sst, &sd, &normal_count, &anomaly_count) == 4) {
            pthread_mutex_lock(&lock);
            /* Route by SD value, not connection order */
            int slot = client_id;
            for (int j = 0; j < MAX_CLIENTS; j++) {
                if (ue_data[j].sd == sd) { slot = j; break; }
            }
            ue_data[slot].sst = sst;
            ue_data[slot].sd = sd;
            ue_data[slot].normal_count = normal_count;
            ue_data[slot].anomaly_count = anomaly_count;
            ue_data[slot].rrc_ue_id = (sd == 1) ? 1 : 2;
            ue_data[slot].updated = true;
            bool all_updated = true;
            for (int j = 0; j < MAX_CLIENTS; j++)
                if (!ue_data[j].updated) { all_updated = false; break; }
            if (all_updated)
                pthread_cond_signal(&cond);
            pthread_mutex_unlock(&lock);

            printf("Parsed values for client %d: SST: %d, SD: %d, Normal: %d, Anomaly: %d\n",
                   client_id + 1, sst, sd, normal_count, anomaly_count);
        } else {
            printf("Failed to parse message from client %d: %s\n", client_id + 1, client_message);
        }
    }

    if (read_size == 0)
        printf("Client %d disconnected\n", client_id + 1);
    else if (read_size == -1)
        perror("recv failed");

    free(client_data);
    return 0;
}

void* rrc_release_ue_thread(void* arg) {
    int ran_ue_id = *((int*)arg);
    char command[256];
    snprintf(command, sizeof(command), "echo rrc release_rrc %d | nc %s 9090", ran_ue_id, g_gnb_telnet_ip);
    system(command);
    free(arg);
    return NULL;
}

void rrc_release_ue(int ran_ue_id) {
    pthread_t thread;
    int* arg = malloc(sizeof(*arg));
    if (arg) {
        *arg = ran_ue_id;
        pthread_create(&thread, NULL, rrc_release_ue_thread, arg);
        pthread_detach(thread);
    }
}

void parse_and_apply_slicing(e2_node_arr_xapp_t nodes) {
    int total_packets[MAX_CLIENTS];
    double anomaly_ratios[MAX_CLIENTS];
    int total_prb = 0;
    int prb_ratio[MAX_CLIENTS];
    int attacker_index = -1;

    for (int i = 0; i < MAX_CLIENTS; i++) {
        total_packets[i] = ue_data[i].normal_count + ue_data[i].anomaly_count;
        anomaly_ratios[i] = (total_packets[i] > 0)
                            ? (double)ue_data[i].anomaly_count / total_packets[i] : 0;
        prb_ratio[i] = (int)((1.0 - anomaly_ratios[i]) * 100);
        total_prb += prb_ratio[i];
        if (anomaly_ratios[i] == 1.0)
            attacker_index = i;
    }

    if (attacker_index != -1) {
        prb_ratio[attacker_index] = 1;  /* 1% floor — cannot send 0 */
        ue_data[attacker_index].prb_ratio = 1;

        total_prb = 0;
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (i != attacker_index) {
                prb_ratio[i] = (int)((1.0 - anomaly_ratios[i]) * 100);
                if (prb_ratio[i] < 1) prb_ratio[i] = 1;
                total_prb += prb_ratio[i];
            }
        }

        if (total_prb > 100) {
            double scaling_factor = 100.0 / total_prb;
            for (int i = 0; i < MAX_CLIENTS; i++) {
                if (i != attacker_index) {
                    prb_ratio[i] = (int)(prb_ratio[i] * scaling_factor);
                    if (prb_ratio[i] < 1) prb_ratio[i] = 1;
                }
            }
        }

        bool changed = false;
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (prb_ratio[i] != ue_data[i].prev_prb_ratio) {
                ue_data[i].prb_ratio = prb_ratio[i];
                ue_data[i].prev_prb_ratio = prb_ratio[i];
                changed = true;
            }
        }
        if (changed)
            enforce_prb_ratio(nodes);

        printf("Client %d (RAN UE ID: %d) has 100%% anomaly. Triggering RRC release.\n",
               attacker_index + 1, ue_data[attacker_index].rrc_ue_id);
        rrc_release_ue(ue_data[attacker_index].rrc_ue_id);

    } else {
        if (total_prb > 100) {
            double scaling_factor = 100.0 / total_prb;
            for (int i = 0; i < MAX_CLIENTS; i++) {
                prb_ratio[i] = (int)(prb_ratio[i] * scaling_factor);
                if (prb_ratio[i] < 1) prb_ratio[i] = 1;
            }
        }

        bool changed = false;
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (prb_ratio[i] != ue_data[i].prev_prb_ratio) {
                ue_data[i].prb_ratio = prb_ratio[i];
                ue_data[i].prev_prb_ratio = prb_ratio[i];
                changed = true;
            }
        }
        if (changed)
            enforce_prb_ratio(nodes);
    }

    for (int i = 0; i < MAX_CLIENTS; i++) {
        printf("Client %d (SST: %d, SD: %d) PRB ratio: %d%%\n",
               i + 1, ue_data[i].sst, ue_data[i].sd, ue_data[i].prb_ratio);
    }
}


int main(int argc, char *argv[]) {
    int socket_desc, new_socket, c;
    struct sockaddr_in server, client;
    int opt = 1;

    pthread_mutex_init(&lock, NULL);
    pthread_cond_init(&cond, NULL);

    for (int i = 0; i < MAX_CLIENTS; i++) {
        ue_data[i].sst = 1;
        ue_data[i].sd = (i == 0) ? 1 : 5;
        ue_data[i].normal_count = 0;
        ue_data[i].anomaly_count = 0;
        ue_data[i].prb_ratio = 50;
        ue_data[i].prev_prb_ratio = 50;
        ue_data[i].updated = false;
    }

    fr_args_t args = init_fr_args(argc, argv);
    load_atd_server_ip(&args);

    init_xapp_api(&args);
    sleep(1);

    e2_node_arr_xapp_t nodes = e2_nodes_xapp_api();
    defer({ free_e2_node_arr_xapp(&nodes); });
    assert(nodes.len > 0);
    printf("Connected E2 nodes = %d\n", nodes.len);

    /* Send initial 50/50 RC SM PRB ratio before ATD connects */
    enforce_prb_ratio(nodes);
    puts("RC SM initialization completed (50/50 PRB ratio).");

    socket_desc = socket(AF_INET, SOCK_STREAM, 0);
    if (socket_desc == -1) {
        printf("Could not create socket");
        return 1;
    }
    puts("Socket created");

    if (setsockopt(socket_desc, SOL_SOCKET, SO_REUSEADDR | SO_REUSEPORT, &opt, sizeof(opt))) {
        perror("setsockopt failed");
        return 1;
    }

    server.sin_family = AF_INET;
    server.sin_addr.s_addr = inet_addr(g_atd_server_ip);
    server.sin_port = htons(PORT);
    printf("ATD Server IP: %s, port: %d\n", g_atd_server_ip, PORT);

    if (bind(socket_desc, (struct sockaddr *)&server, sizeof(server)) < 0) {
        perror("Bind failed. Error");
        return 1;
    }
    puts("Bind done");

    listen(socket_desc, MAX_CLIENTS);
    puts("Waiting for incoming connections...");
    c = sizeof(struct sockaddr_in);

    for (int i = 0; i < MAX_CLIENTS; i++) {
        new_socket = accept(socket_desc, (struct sockaddr *)&client, (socklen_t*)&c);
        if (new_socket < 0) {
            perror("Accept failed");
            return 1;
        }
        printf("Connection accepted from client %d\n", i + 1);

        client_data_t *client_data = (client_data_t*)malloc(sizeof(client_data_t));
        client_data->socket = new_socket;
        client_data->client_id = i;

        pthread_mutex_lock(&lock);
        clients_connected++;
        pthread_cond_signal(&cond);
        pthread_mutex_unlock(&lock);

        pthread_t sniffer_thread;
        if (pthread_create(&sniffer_thread, NULL, client_handler, (void*)client_data) < 0) {
            perror("could not create thread");
            return 1;
        }
        pthread_detach(sniffer_thread);
    }

    pthread_mutex_lock(&lock);
    while (clients_connected < MAX_CLIENTS)
        pthread_cond_wait(&cond, &lock);
    pthread_mutex_unlock(&lock);

    puts("Both clients connected. Starting main loop...");

    while (1) {
        pthread_mutex_lock(&lock);
        bool all_updated = false;
        while (!all_updated) {
            pthread_cond_wait(&cond, &lock);
            all_updated = true;
            for (int j = 0; j < MAX_CLIENTS; j++)
                if (!ue_data[j].updated) { all_updated = false; break; }
        }

        for (int i = 0; i < MAX_CLIENTS; i++) {
            printf("Client %d: SST: %d, SD: %d, Normal: %d, Anomaly: %d\n",
                   i + 1, ue_data[i].sst, ue_data[i].sd,
                   ue_data[i].normal_count, ue_data[i].anomaly_count);
        }

        parse_and_apply_slicing(nodes);

        for (int j = 0; j < MAX_CLIENTS; j++)
            ue_data[j].updated = false;
        pthread_mutex_unlock(&lock);
    }

    close(socket_desc);
    pthread_mutex_destroy(&lock);
    pthread_cond_destroy(&cond);

    while (try_stop_xapp_api() == false)
        usleep(1000);

    return 0;
}
