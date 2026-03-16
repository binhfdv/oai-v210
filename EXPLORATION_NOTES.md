# Exploration Notes — oai-v210 Project

**Last updated**: 2026-03-15 (session 3)

---

## 1. System Architecture Overview

- **Near-RT RIC + xApp** run in the same Docker image: `ddocker122/oai-flexric:detect`
  - Built by: `helm-flexric/nearrt-ric/Dockerfile.rc-prb-rrc-release`
  - Source: clones flexric `slicing-spring-of-code` branch from GitLab at build time
  - Our custom xApp: `helm-flexric/xapp-rc-prb-rrc-release/xapp_rc_slice_ctrl.c`
- **gNB (DU)** runs in image `ddocker122/oai-gnb-slicing:detect`
  - Built by: `helm-flexric/e2-gnb/Dockerfile.slicing`
  - Has custom patches in `helm-flexric/e2-gnb/patches/`
- **Service Models**: ~~SLICE SM (ID=145)~~ → now **RC SM (ID=3)** Style 2 / Action 6 (Slice-level PRB quota) — see §7

---

## 2. RIC Crash: `find_map_xapps_sad: xApp ID not found`

### Symptom
- Near-RT RIC crashes on **second** SLICE SM control message with:
  `Assertion 'xApp ID not found in the tree'` in `find_map_xapps_sad`
- xApp then crashes with `cond_wait_sync_ui: ETIMEDOUT` (5s timeout, no ACK received)

### Crash Location
**File**: `src/ric/iApp/map_xapps_sockaddr.c`, line 194
**Function**: `find_map_xapps_sad(map_xapps_sockaddr_t* m, uint16_t xapp_id)`
```c
it = find_if(tree, it, end, &xapp_id, eq_uint16_wrapper);
assert(it != end && "xApp ID not found in the tree");  // CRASHES HERE
```

### Call Chain
```
DU sends RIC_CONTROL_ACKNOWLEDGE
→ near_ric.c: e2ap_handle_control_ack_ric()
→ near_ric.c: notify_msg_iapp_api()
→ iApp event loop: e2ap_msg_handle_iapp()
→ msg_handler_iapp.c: e2ap_handle_e42_ric_control_ack_iapp()
→ map_xapps_sockaddr.c: find_map_xapps_sad()  ← CRASH
```

### Root Cause (Unresolved)
- `ep.xapps` bimap: left key=`uint16_t xapp_id`, value=`sctp_info_t`
- xApp is assigned `xapp_id=7` at connect time (`generate_setup_response`, `iapp->xapp_id++`)
- `rm_map_xapps_sad` is NEVER called (has `assert(0!=0)` at top — untested)
- Logically xapp_id=7 should always be in the tree
- Root cause not analytically resolved despite full code trace
- xslice-oran has **identical code** — same bug, no fix upstream

### Fix Applied (Defensive Patches)
Created two patch files applied via Dockerfile:

**`helm-flexric/nearrt-ric/patches/map_xapps_sockaddr.c`**
- Changed `find_map_xapps_sad` to return zeroed `sctp_info_t` instead of crashing
- Logs: `[iApp]: WARNING: xapp_id %u not found in xapps table`
- Send fails gracefully (sctp_sendmsg returns -1, prints error), `rm_map_ric_id` still runs

**`helm-flexric/nearrt-ric/patches/sync_ui.c`**
- Changed `cond_wait_sync_ui` to return cleanly on ETIMEDOUT instead of crashing xApp
- Logs: `[xApp]: WARNING: Timeout waiting for E2 Node response`

**`helm-flexric/nearrt-ric/Dockerfile.rc-prb-rrc-release`** updated to:
```dockerfile
COPY nearrt-ric/patches/map_xapps_sockaddr.c /tmp/patches/map_xapps_sockaddr.c
COPY nearrt-ric/patches/sync_ui.c /tmp/patches/sync_ui.c
RUN git clone ... flexric && cd flexric && git checkout slicing-spring-of-code && \
    cp /tmp/xapp_rc_slice_ctrl.c examples/xApp/c/ctrl/ && \
    cp /tmp/patches/map_xapps_sockaddr.c src/ric/iApp/map_xapps_sockaddr.c && \
    cp /tmp/patches/sync_ui.c src/xApp/sync_ui.c && \
    mkdir build && cmake ... && make -j8 && make install
```

---

## 3. xSlice Architecture (from /home/lapdk/workspace/oai-v210/xslice-oran)

### What xSlice Is
- A flexric fork + OAI gNB fork implementing dynamic PRB reallocation via DRL (PPO+GCN)
- RIC/xApp code: `/home/lapdk/workspace/oai-v210/xslice-oran/`
- OAI gNB code: separate repo at `github.com/peihaoY/xSlice_gNB` (NOT in this workspace)

### Key Difference from Our System: SM Used

| | Our System | xSlice |
|--|--|--|
| PRB control SM | SLICE SM (ID=145) `SLICE_CTRL_SM_V0_ADD` | **RC SM (ID=3)** style_type=2, action_id=6 |
| RB addressing | Absolute positions (pos_low, pos_high) | Percentage ratio (Dedicated_PRB_Policy_Ratio) |
| RAN function | `CUSTOMIZED/ran_func_slice.c` | `O-RAN/rc_ctrl_service_style_2.c` |
| DRL interface | TCP socket from anomaly-detection server | Binary file `trandata/slice_ctrl.bin` |

### xSlice Control Message Format (RC SM)

**Control Header Format 1:**
```c
ric_style_type = 2   // Radio Resource Allocation Control
ctrl_act_id = 6      // Slice_level_PRB_quotal_7_6_3_1
```

**Control Message Format 1 — RAN Parameter IDs:**
```c
RRM_Policy_Ratio_List_8_4_3_6 = 1
RRM_Policy_Ratio_Group_8_4_3_6 = 2
RRM_Policy_8_4_3_6 = 3
RRM_Policy_Member_List_8_4_3_6 = 4
RRM_Policy_Member_8_4_3_6 = 5
PLMN_Identity_8_4_3_6 = 6
S_NSSAI_8_4_3_6 = 7
SST_8_4_3_6 = 8
SD_8_4_3_6 = 9
Min_PRB_Policy_Ratio_8_4_3_6 = 10
Max_PRB_Policy_Ratio_8_4_3_6 = 11
Dedicated_PRB_Policy_Ratio_8_4_3_6 = 12  ← THE KEY DYNAMIC VALUE
```

Per-slice config (3 slices: SST=1/SD=1, SST=1/SD=5, SST=1/SD=9):
```c
Min_PRB_Ratio[] = {20, 20, 80}
Max_PRB_Ratio[] = {80, 80, 80}
dedicated_ratio_prb[] = {numbers[0], numbers[1], numbers[2]}  // from DRL
```

### xSlice IPC: trandata/slice_ctrl.bin
Binary file, 4 signed integers (struct.pack('iiii')):
- `[0]` = slice1 PRB % (0-100)
- `[1]` = slice2 PRB % (0-100)
- `[2]` = slice3 PRB % (0-100)
- `[3]` = flag: 0=DRL wrote new action (xApp reads), 1=xApp processed (DRL reads state)

### xSlice OAI gNB: rc_ctrl_service_style_2.c

**CRITICAL FINDING**: This file exists as a compiled `.o` in our OAI build:
```
oai-anomaly-detection/openairinterface5g/cmake_targets/ran_build/build/
  openair2/E2AP/RAN_FUNCTION/CMakeFiles/e2_ran_func_du_cucp_cuup.dir/O-RAN/
  rc_ctrl_service_style_2.c.o
```
But the **SOURCE is missing** from `openair2/E2AP/RAN_FUNCTION/O-RAN/` — only has:
`ran_func_rc.c`, `ran_func_rc_subs.c`, `ran_func_kpm.c`, etc.

Exported function from the .o:
```
T add_mod_rc_slice   ← calls add_mod_dl_slice, set_new_dl_slice_algo
```
Calls into: `nvs_nr_dl_init`, `rrc_gNB_get_ue_context_by_rnti_any_du`

The source must be obtained from `github.com/peihaoY/xSlice_gNB`.

### xSlice End-to-End Flow
```
DRL (ppo.py) → writes slice_ctrl.bin → xApp (xapp_xslice.c) reads it
→ builds RC SM Control Msg (RRM_Policy_Ratio per slice S-NSSAI)
→ control_sm_xapp_api(SM_RC_ID, rc_ctrl)
→ iApp → near-RT RIC → E2 to DU
→ rc_ctrl_service_style_2.c: add_mod_rc_slice()
→ MAC scheduler: updates PRB % per slice
→ KPM indications back to xApp → logged to trandata/KPM_UE.txt
→ DRL reads KPM → computes new action → loop
```

### xSlice xApp Key File
`examples/xApp/c/ctrl/xapp_xslice.c`
- Monitors KPM (subscription)
- Reads binary file for DRL actions
- Sends RC SM control with `gen_rrm_policy_ratio_group()` per slice
- Uses S-NSSAI (SST+SD) to identify each slice

---

## 4. Our xApp: xapp_rc_slice_ctrl.c

**File**: `helm-flexric/xapp-rc-prb-rrc-release/xapp_rc_slice_ctrl.c`

**Current approach:**
- Listens on TCP port 8080 for anomaly-detection server messages
- Message format: `"sst:%d,sd:%d,normal:%d,anomaly:%d"` from each of 2 clients
- Computes PRB allocation based on anomaly ratio: `prb = (1 - anomaly_ratio) * 100`
- Sends SLICE SM ADD with STATIC algorithm and absolute RB positions:
  - Slice 0: `[0 .. rb_boundary-1]`
  - Slice 1: `[rb_boundary .. 105]` (NR_TOTAL_RBS=106)
- Uses `control_sm_xapp_api(SM_SLICE_ID, &ctrl)` — only to DU nodes
- RRC release for 100% anomaly UEs via telnet to `g_atd_server_ip:9090`

**Key constants:**
- `NR_TOTAL_RBS = 106` (dl_carrierBandwidth from DU config)
- `MAX_CLIENTS = 2`
- Default: 50/50 split on startup

---

## 5. OAI gNB Patches

**Location**: `helm-flexric/e2-gnb/patches/`

### ran_func_slice.c (CUSTOMIZED)
Path: `openair2/E2AP/RAN_FUNCTION/CUSTOMIZED/ran_func_slice.c`
- Handles SLICE SM (ID=145) control messages on the DU side
- Calls `nr_slice_table_set(sst, sd, pos_low, pos_high)` for each slice
- Returns `sm_ag_if_ans_t` correctly — **already correct, no changes needed**

### gNB_scheduler_dlsch.c
Patch to DL scheduler for slice-aware scheduling.

### nr_slice_config.c / nr_slice_config.h
Custom slice configuration.

---

## 6. Key flexric Files (submodule: oai-anomaly-detection/flexric)

| File | Purpose | Status |
|------|---------|--------|
| `src/ric/iApp/map_xapps_sockaddr.c` | ep.xapps bimap lookup — CRASH SITE | Patched in nearrt-ric/patches/ |
| `src/xApp/sync_ui.c` | Sync wait for ACK — fatal timeout | Patched in nearrt-ric/patches/ |
| `src/ric/iApp/msg_handler_iapp.c` | iApp message dispatch & control ACK | Crash flows through here |
| `src/ric/iApp/map_ric_id.c` | bimap: near-RIC ric_req_id ↔ xapp_ric_id | Identical to xslice |
| `src/ric/iApp/xapp_ric_id.c` | Comparators — has `eq_xapp_ric_gen_id` bug (line 29 compares m0 with itself) | Bug only in subscription path |
| `src/xApp/e42_xapp.c` | `control_sm_sync_xapp`: sends ctrl, waits 5s | Calls cond_wait_sync_ui |
| `src/ric/near_ric.c` | `fwd_ric_control_request`: assigns ric_req_id++, 3s timer | — |

### iApp Threading Model
- **iApp SCTP thread**: handles xApp messages (control requests)
- **near-RIC event loop thread**: calls `notify_msg_iapp_api` when DU sends ACK
- Both in same process, `map_ric_id` protected by rwlock, `ep.xapps` protected by rwlock

---

## 7. RC SM Migration — COMPLETED (2026-03-15)

Switched xApp from SLICE SM (ID=145) to RC SM (ID=3) Style 2, Action 6 (Slice-level PRB quota).

### Files Changed

**`helm-flexric/e2-gnb/patches/openair2/E2AP/RAN_FUNCTION/O-RAN/rc_ctrl_service_style_2.c`** (NEW)
- Parses RRM Policy Ratio message → calls `nr_slice_table_set(sst, sd, pos_low, pos_high)`
- Converts Dedicated_PRB_Policy_Ratio% to absolute RB positions (cumulative, non-overlapping)
- Include path: `../../../LAYER2/NR_MAC_gNB/nr_slice_config.h` (3 levels up from O-RAN/)

**`helm-flexric/e2-gnb/patches/openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_rc.c`** (NEW PATCH)
- Added `#include "rc_ctrl_service_style_2.h"`
- `fill_rc_control()`: sz_seq_ctrl_style = 2 (added Style 2 / Action 6)
- `write_ctrl_rc_sm()`: replaced `assert(ctrl_act_id==2)` with if-dispatch: action 6 → `add_mod_rc_slice()`

**`helm-flexric/e2-gnb/patches/openair2/E2AP/RAN_FUNCTION/CMakeLists.txt`** (NEW PATCH)
- Added `O-RAN/rc_ctrl_service_style_2.c` to `e2_ran_func_du_cucp_cuup` library

**`helm-flexric/e2-gnb/Dockerfile.slicing`** (UPDATED)
- Added COPY instructions for `ran_func_rc.c`, `rc_ctrl_service_style_2.c/.h`, `RAN_FUNCTION/CMakeLists.txt`

**`helm-flexric/xapp-rc-prb-rrc-release/xapp_rc_slice_ctrl.c`** (REWRITTEN)
- Replaced SLICE SM (`enforce_slicing()`) with RC SM (`enforce_prb_ratio()`)
- Includes: `rc_sm/rc_sm_id.h`, `rc_sm/ie/rc_data_ie.h`, `ran_param_struct.h`, `ran_param_list.h`
- Builds RRM_Policy_Ratio_List with `gen_rrm_policy_ratio_group()` per slice
- Sends `control_sm_xapp_api(..., SM_RC_ID, &rc_ctrl)` to DU+monolithic nodes
- Frees with `free_rc_ctrl_req_data(&rc_ctrl)`
- `prb_ratio` field replaces `prb_allocation` (attacker gets 1% floor, not 0%)

### TODO / Next Steps

- [ ] **Rebuild gNB Docker image**:
  ```
  docker build -f helm-flexric/e2-gnb/Dockerfile.slicing \
    -t ddocker122/oai-gnb-slicing:detect helm-flexric/
  docker push ddocker122/oai-gnb-slicing:detect
  ```
- [ ] **Rebuild RIC+xApp Docker image**:
  ```
  docker build -f helm-flexric/nearrt-ric/Dockerfile.rc-prb-rrc-release \
    -t ddocker122/oai-flexric:detect helm-flexric/
  docker push ddocker122/oai-flexric:detect
  ```
- [ ] **Test** RC SM PRB allocation actually works (verify MAC scheduler updates)
- [ ] **Test** second control message no longer crashes RIC (defensive patches)

---

## 8. Build Commands

```bash
# Rebuild gNB image (RC SM patches + slice scheduler)
docker build \
  -f /home/lapdk/workspace/oai-v210/helm-flexric/e2-gnb/Dockerfile.slicing \
  -t ddocker122/oai-gnb-slicing:detect \
  /home/lapdk/workspace/oai-v210/helm-flexric
docker push ddocker122/oai-gnb-slicing:detect

# Rebuild RIC + xApp image (near-RT RIC and xapp_rc_slice_ctrl)
docker build \
  -f /home/lapdk/workspace/oai-v210/helm-flexric/nearrt-ric/Dockerfile.rc-prb-rrc-release \
  -t ddocker122/oai-flexric:detect \
  /home/lapdk/workspace/oai-v210/helm-flexric
docker push ddocker122/oai-flexric:detect

# Deploy
# (see deploy_anomaly.sh — 'all' = core slices cu ue ric rc)
```

---

## 9. Root Cause Analysis: PRB Allocation Not Working (2026-03-15)

**Last updated**: 2026-03-15 (session 3)

Observed: xApp sends RC SM 60%/1% split → CONTROL-ACK received → both UEs still get equal throughput.

### Bug 1: SD value mismatch (PRB allocation ignored)

**Root cause**: `ngap_gNB_handlers.c` line 760-763 (`InitialContextSetupRequest` path) copies 3 NGAP bytes in order into a `uint32_t` on a little-endian machine — this reverses byte significance.

```c
// BUGGY — byte-order wrong on little-endian x86:
uint8_t *sd_p = (uint8_t *)&msg->pdusession_param[i].nssai.sd;
sd_p[0] = item_p->s_NSSAI.sD->buf[0];  // big-endian MSB → placed at uint32_t LSB!
sd_p[1] = item_p->s_NSSAI.sD->buf[1];
sd_p[2] = item_p->s_NSSAI.sD->buf[2];  // big-endian LSB → placed at uint32_t byte-2!
```

Network encoding of SD=1 is `[0x00, 0x00, 0x01]` (big-endian). Result stored in MAC:
- SD=1 → `uint32_t sd = 0x010000 = 65536` (should be 1)
- SD=5 → `uint32_t sd = 0x050000 = 327680` (should be 5)

The correct macro `BUFFER_TO_INT24` does `(buf[0]<<16)|(buf[1]<<8)|buf[2]` and is used in the `PDUSessionResourceSetupRequest` path (line 978) — but UE initial attach uses the broken path above.

**Effect in scheduler** (`gNB_scheduler_dlsch.c:812`):
```c
slice_found = nr_slice_table_lookup(sched_ctrl_ue->dl_lc_nssai[lc].sd, ...);
// dl_lc_nssai[lc].sd = 65536, but slice table has sd=1 → NO MATCH
// → slice_found = false → rbStart/rbStop never clamped → full RB range for all UEs
```

**Effect in slice table** (`rc_ctrl_service_style_2.c`):
```c
uint32_t sd = (uint32_t)atoi(sd_str);  // "1" → 1, "5" → 5  (correct)
nr_slice_table_set(sst, sd, pos_low, pos_high);
```

The xApp, RC SM, `add_mod_rc_slice`, and `nr_slice_table_set` are all correct. The lookup always fails because the MAC stores SD as 65536 but the slice table has SD as 1.

**Fix applied**: Replaced manual byte-copy in `ngap_gNB_handlers.c:760-763` with `BUFFER_TO_INT24`. Patch copied to `helm-flexric/e2-gnb/patches/openair3/NGAP/ngap_gNB_handlers.c`. COPY instruction added to `Dockerfile.slicing`.

### Bug 2: `nc: not found` (RRC release silently fails)

`xapp_rc_slice_ctrl.c` uses:
```c
snprintf(command, sizeof(command), "echo rrc release_rrc %d | nc %s 9090", ...);
system(command);
```
`nc` (netcat) is not installed in the xApp container (`ddocker122/oai-flexric:detect`).

**Fix applied**: Added `netcat-openbsd` to the runtime apt-get install block in `helm-flexric/nearrt-ric/Dockerfile.rc-prb-rrc-release`.

### Summary

| Problem | Root cause | File | Fix |
|---------|-----------|------|-----|
| PRB allocation ignored | SD byte-order bug → MAC stores `sd=65536` not `sd=1` → lookup always fails | `openair3/NGAP/ngap_gNB_handlers.c:760-763` | ✅ Fixed: use `BUFFER_TO_INT24` |
| RRC release fails | `nc` not installed in xApp container | `nearrt-ric/Dockerfile.rc-prb-rrc-release` | ✅ Fixed: added `netcat-openbsd` |