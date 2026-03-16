#pragma once

#include "../../flexric/src/sm/rc_sm/ie/rc_data_ie.h"
#include "../../flexric/src/sm/agent_if/ans/sm_ag_if_ans.h"

/*
 * RC SM Control Service Style 2, Action 6: Slice-level PRB quota.
 * Called from write_ctrl_rc_sm() when ctrl_act_id == 6.
 */
sm_ag_if_ans_t add_mod_rc_slice(rc_ctrl_req_data_t const* ctrl);
