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
 *
 * RC SM Control Service Style 2: Radio Resource Allocation Control
 * Action 6: Slice-level PRB quota (8.4.3.6 O-RAN E2SM-RC spec)
 *
 * Adapted from xSlice (github.com/peihaoY/xSlice_gNB).
 * Parses the RRM Policy Ratio List and applies per-slice PRB allocation
 * via our custom nr_slice_table_set() → MAC scheduler enforcement.
 */

#include "rc_ctrl_service_style_2.h"

#include "../../flexric/src/sm/rc_sm/ie/rc_data_ie.h"
#include "../../flexric/src/sm/rc_sm/ie/ir/lst_ran_param.h"
#include "../../flexric/src/sm/rc_sm/ie/ir/ran_param_list.h"
#include "../../flexric/src/sm/rc_sm/ie/ir/ran_param_struct.h"
#include "../../flexric/src/sm/rc_sm/ie/ir/ran_parameter_value.h"
#include "../../flexric/src/util/byte_array.h"

#include "../../../LAYER2/NR_MAC_gNB/nr_slice_config.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* RAN Parameter IDs for Slice-level PRB Quota (Table 8.4.3.6, O-RAN E2SM-RC) */
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

/* Total DL RBs in the carrier — must match the gNB config dl_carrierBandwidth */
#define NR_TOTAL_RBS 106

sm_ag_if_ans_t add_mod_rc_slice(rc_ctrl_req_data_t const* ctrl)
{
  assert(ctrl != NULL);
  assert(ctrl->msg.format == FORMAT_1_E2SM_RC_CTRL_MSG);
  assert(ctrl->msg.frmt_1.sz_ran_param >= 1);

  /* ran_param[0] must be the RRM_Policy_Ratio_List */
  const seq_ran_param_t* rrm_list = &ctrl->msg.frmt_1.ran_param[0];
  assert(rrm_list->ran_param_id == RRM_Policy_Ratio_List_8_4_3_6
         && "Expected RRM_Policy_Ratio_List as first RAN parameter");
  assert(rrm_list->ran_param_val.type == LIST_RAN_PARAMETER_VAL_TYPE);
  assert(rrm_list->ran_param_val.lst != NULL);

  const ran_param_list_t* lst = rrm_list->ran_param_val.lst;
  size_t num_slices = lst->sz_lst_ran_param;

  uint16_t cumulative = 0;  /* running RB boundary for non-overlapping slices */

  for (size_t i = 0; i < num_slices; i++) {
    /* Each list entry = one RRM_Policy_Ratio_Group (lst_ran_param_t) */
    const lst_ran_param_t* grp = &lst->lst_ran_param[i];
    assert(grp->ran_param_struct.sz_ran_param_struct == 4
           && "RRM_Policy_Ratio_Group must have 4 RAN parameters");

    const seq_ran_param_t* p = grp->ran_param_struct.ran_param_struct;

    /* ---- Extract SST and SD from p[0] = RRM_Policy ---- */
    assert(p[0].ran_param_id == RRM_Policy_8_4_3_6);
    assert(p[0].ran_param_val.type == STRUCTURE_RAN_PARAMETER_VAL_TYPE);
    assert(p[0].ran_param_val.strct != NULL);
    assert(p[0].ran_param_val.strct->sz_ran_param_struct >= 1);

    const seq_ran_param_t* member_list_param =
        &p[0].ran_param_val.strct->ran_param_struct[0];
    assert(member_list_param->ran_param_id == RRM_Policy_Member_List_8_4_3_6);
    assert(member_list_param->ran_param_val.type == LIST_RAN_PARAMETER_VAL_TYPE);
    assert(member_list_param->ran_param_val.lst != NULL);
    assert(member_list_param->ran_param_val.lst->sz_lst_ran_param >= 1);

    const lst_ran_param_t* member =
        &member_list_param->ran_param_val.lst->lst_ran_param[0];
    assert(member->ran_param_struct.sz_ran_param_struct == 2);

    /* member[1] = S-NSSAI structure (member[0] = PLMN_Identity, skipped) */
    const seq_ran_param_t* s_nssai = &member->ran_param_struct.ran_param_struct[1];
    assert(s_nssai->ran_param_id == S_NSSAI_8_4_3_6);
    assert(s_nssai->ran_param_val.type == STRUCTURE_RAN_PARAMETER_VAL_TYPE);
    assert(s_nssai->ran_param_val.strct != NULL);
    assert(s_nssai->ran_param_val.strct->sz_ran_param_struct == 2);

    const seq_ran_param_t* sst_param = &s_nssai->ran_param_val.strct->ran_param_struct[0];
    const seq_ran_param_t* sd_param  = &s_nssai->ran_param_val.strct->ran_param_struct[1];

    assert(sst_param->ran_param_id == SST_8_4_3_6);
    assert(sst_param->ran_param_val.flag_false != NULL);
    assert(sst_param->ran_param_val.flag_false->type == OCTET_STRING_RAN_PARAMETER_VALUE);
    char* sst_str = cp_ba_to_str(sst_param->ran_param_val.flag_false->octet_str_ran);
    uint8_t sst = (uint8_t)atoi(sst_str);
    free(sst_str);

    assert(sd_param->ran_param_id == SD_8_4_3_6);
    assert(sd_param->ran_param_val.flag_false != NULL);
    assert(sd_param->ran_param_val.flag_false->type == OCTET_STRING_RAN_PARAMETER_VALUE);
    char* sd_str = cp_ba_to_str(sd_param->ran_param_val.flag_false->octet_str_ran);
    uint32_t sd = (uint32_t)atoi(sd_str);
    free(sd_str);

    /* ---- Extract Dedicated_PRB_Policy_Ratio from p[3] ---- */
    assert(p[3].ran_param_id == Dedicated_PRB_Policy_Ratio_8_4_3_6);
    assert(p[3].ran_param_val.type == ELEMENT_KEY_FLAG_FALSE_RAN_PARAMETER_VAL_TYPE);
    assert(p[3].ran_param_val.flag_false != NULL);
    assert(p[3].ran_param_val.flag_false->type == INTEGER_RAN_PARAMETER_VALUE);
    int64_t ratio = p[3].ran_param_val.flag_false->int_ran;

    /* Clamp ratio to [1..100] */
    if (ratio < 1)   ratio = 1;
    if (ratio > 100) ratio = 100;

    /* Convert percentage → absolute RB positions (cumulative, non-overlapping) */
    uint16_t num_rbs = (uint16_t)((ratio * NR_TOTAL_RBS + 50) / 100);
    if (num_rbs < 1) num_rbs = 1;

    uint16_t pos_low  = cumulative;
    uint16_t pos_high = cumulative + num_rbs - 1;
    if (pos_high >= NR_TOTAL_RBS) pos_high = NR_TOTAL_RBS - 1;

    printf("[RC-SS2]: slice sst=%u sd=%u dedicated=%ld%% -> RBs [%u..%u]\n",
           sst, sd, ratio, pos_low, pos_high);
    fflush(stdout);

    nr_slice_table_set(sst, sd, pos_low, pos_high);

    cumulative = pos_high + 1;
    if (cumulative >= NR_TOTAL_RBS) break;
  }

  sm_ag_if_ans_t ans = {.type = CTRL_OUTCOME_SM_AG_IF_ANS_V0};
  ans.ctrl_out.type = RAN_CTRL_V1_3_AGENT_IF_CTRL_ANS_V0;
  return ans;
}
