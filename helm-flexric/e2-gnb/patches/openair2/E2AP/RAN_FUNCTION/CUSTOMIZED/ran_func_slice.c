/*
 * Licensed to the OpenAirInterface (OAI) Software Alliance under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The OpenAirInterface Software Alliance licenses this file to You under
 * the OAI Public License, Version 1.1  (the "License"); you may not use this file
 * except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.openairinterface.org/?page_id=698
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *-------------------------------------------------------------------------------
 * For more information about the OpenAirInterface (OAI) Software Alliance:
 *      contact@openairinterface.org
 */

#include "ran_func_slice.h"
#include "../../flexric/test/rnd/fill_rnd_data_slice.h"
#include "../../../LAYER2/NR_MAC_gNB/nr_slice_config.h"
#include <assert.h>
#include <stdio.h>

bool read_slice_sm(void* data)
{
  assert(data != NULL);
//  assert(data->type == SLICE_STATS_V0);

  slice_ind_data_t* slice = (slice_ind_data_t*)data;
  fill_slice_ind_data(slice);

  return true;
}

void read_slice_setup_sm(void* data)
{
  assert(data != NULL);
//  assert(data->type == SLICE_AGENT_IF_E2_SETUP_ANS_V0 );

  assert(0 !=0 && "Not supported");
}

sm_ag_if_ans_t write_ctrl_slice_sm(void const* data)
{
  assert(data != NULL);

  slice_ctrl_req_data_t const* slice_req_ctrl = (slice_ctrl_req_data_t const*)data;
  slice_ctrl_msg_t const* msg = &slice_req_ctrl->msg;

  if (msg->type == SLICE_CTRL_SM_V0_ADD) {
    printf("[E2 Agent]: SLICE CONTROL ADD rx\n");

    const ul_dl_slice_conf_t *dl_conf = &msg->u.add_mod_slice.dl;
    for (uint32_t i = 0; i < dl_conf->len_slices; i++) {
      const fr_slice_t *sl = &dl_conf->slices[i];

      if (sl->params.type != SLICE_ALG_SM_V0_STATIC) {
        printf("[E2 Agent]: slice id %u: only STATIC algorithm supported, skipping\n", sl->id);
        continue;
      }

      /* Slice id encodes sst in bits [7:0], sd in bits [31:8] */
      uint8_t  sst = (uint8_t)(sl->id & 0xFF);
      uint32_t sd  = (sl->id >> 8) & 0xFFFFFF;

      uint16_t pos_low  = (uint16_t)sl->params.u.sta.pos_low;
      uint16_t pos_high = (uint16_t)sl->params.u.sta.pos_high;

      if (pos_low > pos_high) {
        printf("[E2 Agent]: slice id %u: pos_low %u > pos_high %u, skipping\n",
               sl->id, pos_low, pos_high);
        continue;
      }

      nr_slice_table_set(sst, sd, pos_low, pos_high);
      printf("[E2 Agent]: slice (sst=%u sd=%u) -> RBs [%u..%u] applied\n",
             sst, sd, pos_low, pos_high);
    }

  } else if (msg->type == SLICE_CTRL_SM_V0_DEL) {
    printf("[E2 Agent]: SLICE CONTROL DEL rx (not implemented)\n");
  } else if (msg->type == SLICE_CTRL_SM_V0_UE_SLICE_ASSOC) {
    printf("[E2 Agent]: SLICE CONTROL ASSOC rx (not implemented)\n");
  } else {
    assert(0 != 0 && "Unknown msg_type!");
  }

  sm_ag_if_ans_t ans = {.type = CTRL_OUTCOME_SM_AG_IF_ANS_V0};
  ans.ctrl_out.type = SLICE_AGENT_IF_CTRL_ANS_V0;
  return ans;
}


