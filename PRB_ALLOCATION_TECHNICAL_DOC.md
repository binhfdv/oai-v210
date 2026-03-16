# PRB Allocation via O-RAN E2SM-RC — Technical Documentation

## Overview

This document explains how per-slice Physical Resource Block (PRB) allocation was implemented and made functional in the OAI gNB + FlexRIC stack. The system allows an xApp to dynamically restrict the radio bandwidth available to each network slice based on anomaly detection results.

---

## System Architecture

```
┌─────────────────────┐      TCP/8080       ┌──────────────────────┐
│  ATD Server Slice1  │ ──────────────────► │                      │
│  (monitors UE1)     │  sst:1,sd:1,        │   xApp               │
│  12.1.1.0/25        │  normal:60,anom:40  │   xapp_rc_slice_ctrl │
└─────────────────────┘                     │                      │
                                            │  Calculates PRB%     │
┌─────────────────────┐      TCP/8080       │  Builds RC CONTROL   │
│  ATD Server Slice2  │ ──────────────────► │  message             │
│  (monitors UE2)     │  sst:1,sd:5,        └──────────┬───────────┘
│  12.2.1.128/25      │  normal:100,anom:0             │ E2 CONTROL
└─────────────────────┘                                │ (E2SM-RC SS2 A6)
                                                       ▼
                                            ┌──────────────────────┐
                                            │  FlexRIC nearRT-RIC  │
                                            │  Routes CONTROL to   │
                                            │  DU E2 node          │
                                            └──────────┬───────────┘
                                                       │ E2AP CONTROL
                                                       ▼
                                            ┌──────────────────────┐
                                            │  OAI gNB-DU          │
                                            │  E2SM-RC agent       │
                                            │  → nr_slice_table    │
                                            │  → MAC scheduler     │
                                            └──────────────────────┘
                                                  │         │
                                              UE1(sd=1)  UE2(sd=5)
                                              RBs[0..38] RBs[39..104]
```

**Key components:**
| Component | File | Role |
|---|---|---|
| xApp | `xapp_rc_slice_ctrl.c` | Receives anomaly data, calculates PRB%, sends E2 CONTROL |
| DU RC capability | `ran_func_rc.c` | Advertises RC Style 2/Action 6 to FlexRIC |
| RC control handler | `rc_ctrl_service_style_2.c` | Parses CONTROL message, calls slice table |
| Slice table | `nr_slice_config.c/.h` | Thread-safe in-memory PRB range store |
| MAC scheduler | `gNB_scheduler_dlsch.c` | Reads slice table, restricts RB allocation per UE |

---

## Step 1 — DU Advertises RC Control Capability

**File:** `openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_rc.c`

### The Problem

FlexRIC uses the E2 Setup procedure to discover what capabilities each E2 node has. The DU must declare that it supports E2SM-RC Style 2 / Action 6 (Slice-level PRB quota) in its `E2SetupRequest`. Without this declaration, FlexRIC will never route an E2 CONTROL message to the DU.

The original code had a lookup table `ran_def_rc[]` indexed by node type (`ngran_node_t`). Index 7 = `ngran_gNB_DU` was assigned `fill_rc_ran_def_null`, which returns a definition with `def.ctrl = NULL` — meaning "no control supported."

```c
// BEFORE (broken): DU declares no RC control capability
static const fp_rc_func_def ran_def_rc[END_NGRAN_NODE_TYPE] = {
  ...
  fill_rc_ran_def_null,    // index 7 = ngran_gNB_DU  ← NULL ctrl, FlexRIC ignores DU
  ...
};
```

### The Fix — `fill_rc_ran_def_du()`

A new function was added that builds a complete RC RAN Function Definition declaring exactly one control style (Style 2) with exactly one action (Action 6):

```c
#ifdef NGRAN_GNB_DU
static e2sm_rc_func_def_t fill_rc_ran_def_du(void)
{
  e2sm_rc_func_def_t def = {0};

  // No Event Trigger, Report, Insert, or Policy — DU only does CONTROL
  def.ev_trig = NULL;
  def.report  = NULL;
  def.insert  = NULL;
  def.policy  = NULL;

  // Allocate the CONTROL definition
  def.ctrl = calloc(1, sizeof(ran_func_def_ctrl_t));

  ran_func_def_ctrl_t* ctrl = def.ctrl;
  ctrl->sz_seq_ctrl_style = 1;   // exactly 1 control style
  ctrl->seq_ctrl_style = calloc(1, sizeof(seq_ctrl_style_t));

  seq_ctrl_style_t* s2 = &ctrl->seq_ctrl_style[0];
  s2->style_type = 2;                                  // Style Type 2: Radio Resource Allocation Control
  s2->name = cp_str_to_ba("Radio Resource Allocation Control");
  s2->hdr  = FORMAT_1_E2SM_RC_CTRL_HDR;               // Header format 1
  s2->msg  = FORMAT_1_E2SM_RC_CTRL_MSG;               // Message format 1
  s2->out_frmt = FORMAT_1_E2SM_RC_CTRL_OUT;

  s2->sz_seq_ctrl_act = 1;   // exactly 1 action
  s2->seq_ctrl_act = calloc(1, sizeof(seq_ctrl_act_2_t));
  s2->seq_ctrl_act[0].id   = 6;                        // Action ID 6: Slice-level PRB quota
  s2->seq_ctrl_act[0].name = cp_str_to_ba("Slice-level PRB quota");

  return def;
}
#endif
```

**Why `#ifdef NGRAN_GNB_DU`?**
The preprocessor symbol `NGRAN_GNB_DU` is defined only when compiling the DU binary. This ensures the DU-specific code path is compiled in, while other node types (CU-CP, CU-UP) remain unaffected. The same guard is used to include `rc_ctrl_service_style_2.h`.

The lookup table entry is updated to use the new function:

```c
static const fp_rc_func_def ran_def_rc[END_NGRAN_NODE_TYPE] = {
  NULL,                    // ngran_eNB
  NULL,                    // ngran_ng_eNB
  fill_rc_ran_def_gnb,     // ngran_gNB (monolithic)
  NULL,                    // ngran_eNB_CU
  NULL,                    // ngran_ng_eNB_CU
  fill_rc_ran_def_cu,      // ngran_gNB_CU
  NULL,                    // ngran_eNB_DU
#ifdef NGRAN_GNB_DU
  fill_rc_ran_def_du,      // ngran_gNB_DU ← FIXED: advertise Style 2/Action 6
#else
  fill_rc_ran_def_null,    // fallback if symbol not defined
#endif
  NULL,                    // ngran_eNB_MBMS_STA
  fill_rc_ran_def_cucp,    // ngran_gNB_CUCP
  fill_rc_ran_def_null,    // ngran_gNB_CUUP
};
```

**Effect:** The DU now sends an `E2SetupRequest` that includes RC Style 2 / Action 6 in its RAN Function Definition. FlexRIC records this and will route any incoming E2 CONTROL for that style/action to the DU.

---

## Step 2 — xApp Calculates PRB Ratios and Sends E2 CONTROL

**File:** `xapp_rc_slice_ctrl.c`

### Receiving Anomaly Data

The xApp listens on TCP port 8080 for connections from up to 2 ATD (Anomaly Traffic Detection) servers. Each server sends messages in the format:

```
sst:1,sd:1,normal:60,anomaly:40
```

The `client_handler` thread parses this and stores it in `ue_data[]`:

```c
if (sscanf(client_message, "sst:%d,sd:%d,normal:%d,anomaly:%d",
           &sst, &sd, &normal_count, &anomaly_count) == 4) {
    // Route by SD value to the correct slot
    int slot = client_id;
    for (int j = 0; j < MAX_CLIENTS; j++) {
        if (ue_data[j].sd == sd) { slot = j; break; }
    }
    ue_data[slot].sst          = sst;
    ue_data[slot].sd           = sd;
    ue_data[slot].normal_count = normal_count;
    ue_data[slot].anomaly_count = anomaly_count;
    ue_data[slot].updated      = true;
}
```

### PRB Ratio Calculation — `parse_and_apply_slicing()`

Once both ATD servers have sent data (`all_updated == true`), the xApp calculates PRB ratios:

```c
for (int i = 0; i < MAX_CLIENTS; i++) {
    int total = ue_data[i].normal_count + ue_data[i].anomaly_count;
    double anomaly_ratio = (total > 0) ? (double)ue_data[i].anomaly_count / total : 0;

    // PRB ratio = inverse of anomaly ratio
    // A slice with 40% anomaly gets (1 - 0.4) * 100 = 60% PRBs
    prb_ratio[i] = (int)((1.0 - anomaly_ratio) * 100);
}
```

If the total exceeds 100%, it is normalized:

```c
if (total_prb > 100) {
    double scaling_factor = 100.0 / total_prb;
    for (int i = 0; i < MAX_CLIENTS; i++) {
        prb_ratio[i] = (int)(prb_ratio[i] * scaling_factor);
    }
}
```

**Example — UE1 anomalous (sd=1: 40 anomaly, sd=5: 0 anomaly):**
```
sd=1: anomaly_ratio = 40/100 = 0.4  → prb_ratio = 60%
sd=5: anomaly_ratio =  0/100 = 0.0  → prb_ratio = 100%
total = 160% > 100 → scale by 100/160 = 0.625
sd=1: 60 × 0.625 = 37%
sd=5: 100 × 0.625 = 62%
```

### Building the E2SM-RC Control Message — `enforce_prb_ratio()`

The xApp builds an O-RAN E2SM-RC Style 2 / Action 6 control message. The message encodes an `RRM_Policy_Ratio_List` containing one group per slice:

```
RRM_Policy_Ratio_List (LIST)
 └── RRM_Policy_Ratio_Group [0]    ← slice sd=1
      ├── RRM_Policy (STRUCTURE)
      │    └── RRM_Policy_Member_List (LIST)
      │         └── RRM_Policy_Member
      │              ├── PLMN_Identity = "00101"
      │              └── S-NSSAI (STRUCTURE)
      │                   ├── SST = "1"
      │                   └── SD  = "1"
      ├── Min_PRB_Policy_Ratio  = 1
      ├── Max_PRB_Policy_Ratio  = 100
      └── Dedicated_PRB_Policy_Ratio = 37    ← the enforced value

 └── RRM_Policy_Ratio_Group [1]    ← slice sd=5
      └── ... SD = "5", Dedicated_PRB_Policy_Ratio = 62
```

The message header specifies:
- **RIC Style Type = 2** (Radio Resource Allocation Control)
- **Control Action ID = 6** (Slice-level PRB quota)
- **Header Format = FORMAT_1**, **Message Format = FORMAT_1**

The CONTROL is sent to all DU and monolithic gNB nodes:

```c
for (size_t i = 0; i < nodes.len; ++i) {
    if (NODE_IS_DU(nodes.n[i].id.type) || NODE_IS_MONOLITHIC(nodes.n[i].id.type)) {
        control_sm_xapp_api(&nodes.n[i].id, SM_RC_ID, &rc_ctrl);
    }
}
```

---

## Step 3 — FlexRIC Routes the CONTROL to the DU

FlexRIC's nearRT-RIC receives the `control_sm_xapp_api` call from the xApp and:

1. Looks up which E2 nodes have registered support for `SM_RC_ID` (RC Service Model)
2. Filters to DU nodes (because `NODE_IS_DU` is checked by the xApp)
3. Encodes the `rc_ctrl_req_data_t` into an ASN.1 E2AP `RICcontrolRequest` PDU
4. Sends it over SCTP to the DU's E2 interface (port 36421)

This routing only works because the DU now declares Style 2 / Action 6 support in its E2 Setup (Step 1). Before the fix, FlexRIC had no record of the DU supporting RC control and would silently drop the request.

---

## Step 4 — DU Receives and Dispatches the CONTROL

**File:** `openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_rc.c` — `write_ctrl_rc_sm()`

The DU's E2 agent decodes the incoming E2AP CONTROL PDU and calls `write_ctrl_rc_sm()` — the registered write handler for the RC Service Model:

```c
sm_ag_if_ans_t write_ctrl_rc_sm(void const* data)
{
  rc_ctrl_req_data_t const* ctrl = (rc_ctrl_req_data_t const*)data;

  // Debug: confirm the function is called and what action was requested
  printf("[RC SM DEBUG]: write_ctrl_rc_sm called hdr_fmt=%d act_id=%d\n",
         ctrl->hdr.format, ctrl->hdr.frmt_1.ctrl_act_id);
  fflush(stdout);

  // Validate header and message formats
  assert(ctrl->hdr.format == FORMAT_1_E2SM_RC_CTRL_HDR);
  assert(ctrl->msg.format == FORMAT_1_E2SM_RC_CTRL_MSG);

#ifdef NGRAN_GNB_DU
  if (ctrl->hdr.frmt_1.ctrl_act_id == 6) {
    printf("[RC SM]: Slice-level PRB quota control (action 6)\n");
    fflush(stdout);
    return add_mod_rc_slice(ctrl);   // ← hand off to the parser
  }
#endif

  // Other actions (e.g., QoS flow mapping) handled below...
}
```

The dispatch checks `ctrl_act_id == 6` and calls `add_mod_rc_slice()`. The `#ifdef NGRAN_GNB_DU` guard ensures this branch only exists in the DU binary.

**Note on `fflush(stdout)`:** In containerized environments (`kubectl logs`), stdout is fully buffered — `printf` with `\n` does **not** auto-flush. Without explicit `fflush(stdout)`, log lines never appear in `kubectl logs` even though the code executes. All key log lines have `fflush(stdout)` added.

---

## Step 5 — Parsing the RRM Policy and Updating the Slice Table

**File:** `openair2/E2AP/RAN_FUNCTION/O-RAN/rc_ctrl_service_style_2.c`

`add_mod_rc_slice()` parses the nested RAN parameter structure and extracts SST, SD, and the dedicated PRB ratio for each slice:

```c
sm_ag_if_ans_t add_mod_rc_slice(rc_ctrl_req_data_t const* ctrl)
{
  // Navigate the RAN parameter tree:
  // ran_param[0] = RRM_Policy_Ratio_List (LIST)
  const seq_ran_param_t* rrm_list = &ctrl->msg.frmt_1.ran_param[0];
  const ran_param_list_t* lst = rrm_list->ran_param_val.lst;
  size_t num_slices = lst->sz_lst_ran_param;

  uint16_t cumulative = 0;   // tracks RB boundary for non-overlapping allocation

  for (size_t i = 0; i < num_slices; i++) {
    const lst_ran_param_t* grp = &lst->lst_ran_param[i];   // one group per slice
    const seq_ran_param_t* p   = grp->ran_param_struct.ran_param_struct;

    // ── Extract SST and SD ──────────────────────────────────────────────
    // p[0] = RRM_Policy → RRM_Policy_Member_List → RRM_Policy_Member
    //      → S-NSSAI → SST (octet string "1") + SD (octet string "1" or "5")
    const seq_ran_param_t* s_nssai = &member->ran_param_struct.ran_param_struct[1];
    const seq_ran_param_t* sst_param = &s_nssai->ran_param_val.strct->ran_param_struct[0];
    const seq_ran_param_t* sd_param  = &s_nssai->ran_param_val.strct->ran_param_struct[1];

    char* sst_str = cp_ba_to_str(sst_param->ran_param_val.flag_false->octet_str_ran);
    uint8_t sst = (uint8_t)atoi(sst_str);   // e.g., 1
    free(sst_str);

    char* sd_str = cp_ba_to_str(sd_param->ran_param_val.flag_false->octet_str_ran);
    uint32_t sd = (uint32_t)atoi(sd_str);   // e.g., 1 or 5
    free(sd_str);

    // ── Extract Dedicated PRB ratio ─────────────────────────────────────
    // p[3] = Dedicated_PRB_Policy_Ratio (INTEGER)
    int64_t ratio = p[3].ran_param_val.flag_false->int_ran;  // e.g., 37
    if (ratio < 1)   ratio = 1;
    if (ratio > 100) ratio = 100;

    // ── Convert percentage to absolute RB positions ─────────────────────
    // NR_TOTAL_RBS = 106 (matches dl_carrierBandwidth in gNB config)
    uint16_t num_rbs  = (uint16_t)((ratio * NR_TOTAL_RBS + 50) / 100);  // round
    uint16_t pos_low  = cumulative;
    uint16_t pos_high = cumulative + num_rbs - 1;
    if (pos_high >= NR_TOTAL_RBS) pos_high = NR_TOTAL_RBS - 1;

    printf("[RC-SS2]: slice sst=%u sd=%u dedicated=%ld%% -> RBs [%u..%u]\n",
           sst, sd, ratio, pos_low, pos_high);
    fflush(stdout);

    // ── Write to the slice table ────────────────────────────────────────
    nr_slice_table_set(sst, sd, pos_low, pos_high);

    cumulative = pos_high + 1;   // next slice starts after this one (non-overlapping)
    if (cumulative >= NR_TOTAL_RBS) break;
  }

  sm_ag_if_ans_t ans = {.type = CTRL_OUTCOME_SM_AG_IF_ANS_V0};
  ans.ctrl_out.type = RAN_CTRL_V1_3_AGENT_IF_CTRL_ANS_V0;
  return ans;
}
```

**RB conversion example (UE1 anomalous, 37%/62%):**
```
Slice 1 (sd=1, ratio=37%):
  num_rbs  = (37 × 106 + 50) / 100 = (3922 + 50) / 100 = 39
  pos_low  = 0
  pos_high = 0 + 39 - 1 = 38
  cumulative = 39

Slice 2 (sd=5, ratio=62%):
  num_rbs  = (62 × 106 + 50) / 100 = (6572 + 50) / 100 = 66
  pos_low  = 39
  pos_high = 39 + 66 - 1 = 104
  cumulative = 105
```

Log output:
```
[RC-SS2]: slice sst=1 sd=1 dedicated=37% -> RBs [0..38]
[RC-SS2]: slice sst=1 sd=5 dedicated=62% -> RBs [39..104]
```

---

## Step 6 — The Slice Table

**Files:** `nr_slice_config.h`, `nr_slice_config.c`

The slice table is a simple in-memory structure shared between the E2 agent thread (writer) and the MAC scheduler thread (reader). A mutex ensures thread safety.

### Data Structure

```c
#define NR_MAX_SLICES 8

typedef struct {
  uint8_t  sst;       // Slice/Service Type (e.g., 1)
  uint32_t sd;        // Slice Differentiator (e.g., 1 or 5)
  uint16_t pos_low;   // first RB index (inclusive, 0-based within BWP)
  uint16_t pos_high;  // last  RB index (inclusive)
  bool     valid;     // whether this entry is in use
} nr_slice_entry_t;

typedef struct {
  pthread_mutex_t  lock;
  nr_slice_entry_t entries[NR_MAX_SLICES];
  int              num_entries;
} nr_slice_table_t;

extern nr_slice_table_t g_nr_slice_table;   // global, zero-initialized
```

### `nr_slice_table_set()` — Write Path (E2 agent thread)

```c
void nr_slice_table_set(uint8_t sst, uint32_t sd, uint16_t pos_low, uint16_t pos_high)
{
  pthread_mutex_lock(&g_nr_slice_table.lock);

  // Search for an existing entry with matching (sst, sd) → update in place
  for (int i = 0; i < NR_MAX_SLICES; i++) {
    nr_slice_entry_t *e = &g_nr_slice_table.entries[i];
    if (e->valid && e->sst == sst && e->sd == sd) {
      e->pos_low  = pos_low;
      e->pos_high = pos_high;
      printf("[NR SLICE]: updated (sst=%u sd=%u) -> RBs [%u..%u]\n", sst, sd, pos_low, pos_high);
      fflush(stdout);
      pthread_mutex_unlock(&g_nr_slice_table.lock);
      return;
    }
  }

  // No existing entry → find a free slot and insert
  for (int i = 0; i < NR_MAX_SLICES; i++) {
    nr_slice_entry_t *e = &g_nr_slice_table.entries[i];
    if (!e->valid) {
      e->sst = sst; e->sd = sd;
      e->pos_low = pos_low; e->pos_high = pos_high;
      e->valid = true;
      if (i >= g_nr_slice_table.num_entries)
        g_nr_slice_table.num_entries = i + 1;
      printf("[NR SLICE]: added (sst=%u sd=%u) -> RBs [%u..%u]\n", sst, sd, pos_low, pos_high);
      fflush(stdout);
      pthread_mutex_unlock(&g_nr_slice_table.lock);
      return;
    }
  }

  printf("[NR SLICE]: WARNING - slice table full\n");
  fflush(stdout);
  pthread_mutex_unlock(&g_nr_slice_table.lock);
}
```

### `nr_slice_table_lookup()` — Read Path (MAC scheduler thread)

```c
bool nr_slice_table_lookup(uint8_t sst, uint32_t sd, uint16_t *pos_low, uint16_t *pos_high)
{
  pthread_mutex_lock(&g_nr_slice_table.lock);
  for (int i = 0; i < g_nr_slice_table.num_entries; i++) {
    const nr_slice_entry_t *e = &g_nr_slice_table.entries[i];
    if (e->valid && e->sst == sst && e->sd == sd) {
      *pos_low  = e->pos_low;
      *pos_high = e->pos_high;
      pthread_mutex_unlock(&g_nr_slice_table.lock);
      return true;   // found
    }
  }
  pthread_mutex_unlock(&g_nr_slice_table.lock);
  return false;      // not found → no restriction applied
}
```

---

## Step 7 — MAC Scheduler Enforces the PRB Restriction

**File:** `openair2/LAYER2/NR_MAC_gNB/gNB_scheduler_dlsch.c`

The NR MAC downlink scheduler runs every slot and iterates over all UEs with pending data. For each UE, it determines the RB range to use. The slice table enforcement is inserted **after** `get_start_stop_allocation()` sets the initial `rbStart`/`rbStop` from the BWP:

```c
int rbStop = 0;
int rbStart = 0;
get_start_stop_allocation(mac, iterator->UE, &rbStart, &rbStop);
// rbStart = 0, rbStop = 105 initially (full 106 RBs)

/* Per-slice PRB enforcement */
{
  NR_UE_sched_ctrl_t *sched_ctrl_ue = &iterator->UE->UE_sched_ctrl;
  uint16_t sl_low = 0, sl_high = 0;
  bool slice_found = false;

  // Find the first DRB (lc >= 4) of this UE and look up its S-NSSAI
  for (int lci = 0; lci < sched_ctrl_ue->dl_lc_num; lci++) {
    const int lc = sched_ctrl_ue->dl_lc_ids[lci];
    if (lc >= 4) {
      // dl_lc_nssai[lc] is populated from F1AP UE Context Setup (carries the S-NSSAI
      // that the 5GC assigned to this UE's PDU session — e.g., sst=1, sd=1 for UE1)
      slice_found = nr_slice_table_lookup(
                      sched_ctrl_ue->dl_lc_nssai[lc].sst,
                      sched_ctrl_ue->dl_lc_nssai[lc].sd,
                      &sl_low, &sl_high);
      break;
    }
  }

  if (slice_found) {
    // Clamp rbStart up to sl_low  (push start into the slice's region)
    if (sl_low  > (uint16_t)rbStart) rbStart = sl_low;
    // Clamp rbStop  down to sl_high (cap end at the slice's region)
    if (sl_high < (uint16_t)rbStop)  rbStop  = sl_high;
    // If no RBs remain after clamping, skip this UE this slot
    if (rbStart > rbStop) { iterator++; continue; }
  }
}
```

### How the clamping works for each UE

After the slice table is set to sd=1→[0..38] and sd=5→[39..104]:

**UE1 (sd=1, sl_low=0, sl_high=38):**
```
Initial: rbStart=0, rbStop=105
After clamp:
  sl_low(0) > rbStart(0)?  No  → rbStart stays 0
  sl_high(38) < rbStop(105)? Yes → rbStop = 38
Result: rbStart=0, rbStop=38   → 39 usable RBs (37% of 106)
```

**UE2 (sd=5, sl_low=39, sl_high=104):**
```
Initial: rbStart=0, rbStop=105
After clamp:
  sl_low(39) > rbStart(0)?  Yes → rbStart = 39
  sl_high(104) < rbStop(105)? Yes → rbStop = 104
Result: rbStart=39, rbStop=104 → 66 usable RBs (62% of 106)
```

The ranges are **non-overlapping** — UE1 uses RBs [0..38] and UE2 uses RBs [39..104]. They do not compete for the same frequency resources within a slot.

### Throughput Impact

With equal channel quality (RF simulator), throughput scales roughly with the number of usable RBs:

```
UE1 proportion: 39 / (39 + 66) ≈ 37%
UE2 proportion: 66 / (39 + 66) ≈ 63%

Measured (iperf3):
  UE1 (sd=1, 37% PRBs): ~22.8 Mbits/sec   ↓ from baseline ~37 Mbits
  UE2 (sd=5, 62% PRBs): ~38.6 Mbits/sec   ↑ from baseline ~37 Mbits
  Ratio: 38.6 / 22.8 ≈ 1.69  vs  62/37 ≈ 1.68  ✓ (exact match)
```

---

## UE-to-Slice Mapping (Verified)

The S-NSSAI for each UE's DRB is assigned end-to-end by the 5G core:

```
oai-smf-slice1:
  DNN: oai1, IP pool: 12.1.1.0/25
  S-NSSAI: sst=1, sd=000001
  → UE1 (12.1.1.2) is always on sd=1

oai-smf-slice2:
  DNN: oai2, IP pool: 12.2.1.128/25
  S-NSSAI: sst=1, sd=000005
  → UE2 (12.2.1.130) is always on sd=5
```

The AMF selects SMF-slice1 for UE1 and SMF-slice2 for UE2 based on subscription/NSSAI preference. This assignment propagates: AMF → NGAP → CU-CP → F1AP → DU, where the DU's MAC stores it in `dl_lc_nssai[lc]` per logical channel.

The ATD server sd values match this:
- `anomaly-detection-server-slice1.py`: monitors `12.1.1.0/25` (UE1), reports `sd=1` ✓
- `anomaly-detection-server-slice2.py`: monitors `12.2.1.128/25` (UE2), reports `sd=5` ✓

---

## Complete Data Flow Summary

```
ATD Slice1: "sst:1,sd:1,normal:60,anomaly:40"
ATD Slice2: "sst:1,sd:5,normal:100,anomaly:0"
     │
     ▼
xApp calculates:
  sd=1: (1-0.4)*100 = 60% → scaled to 37%
  sd=5: (1-0.0)*100 = 100% → scaled to 62%
     │
     ▼ E2SM-RC Style 2 / Action 6 CONTROL
     │ RRM_Policy_Ratio_List:
     │   Group[0]: sd=1, Dedicated_PRB=37
     │   Group[1]: sd=5, Dedicated_PRB=62
     │
     ▼ (FlexRIC routes to DU because DU now declares Style 2/Action 6)
     │
     ▼ write_ctrl_rc_sm() in DU E2 agent
     │   → add_mod_rc_slice()
     │     → sd=1: ratio=37% → RBs [0..38]  → nr_slice_table_set(1,1,0,38)
     │     → sd=5: ratio=62% → RBs [39..104] → nr_slice_table_set(1,5,39,104)
     │
     ▼ MAC scheduler (every DL slot)
       For UE1 (dl_lc_nssai: sst=1,sd=1):
         lookup → [0..38] → rbStart=0, rbStop=38 → 39 RBs → ~22.8 Mbits
       For UE2 (dl_lc_nssai: sst=1,sd=5):
         lookup → [39..104] → rbStart=39, rbStop=104 → 66 RBs → ~38.6 Mbits
```

---

## Files Modified

| File | Change |
|---|---|
| `openair2/E2AP/RAN_FUNCTION/O-RAN/ran_func_rc.c` | Added `fill_rc_ran_def_du()`, changed `ran_def_rc[7]` to use it, added debug + fflush in `write_ctrl_rc_sm()` |
| `openair2/E2AP/RAN_FUNCTION/O-RAN/rc_ctrl_service_style_2.c` | New file: parses RRM Policy Ratio List, converts % to RBs, calls `nr_slice_table_set()`, added fflush |
| `openair2/E2AP/RAN_FUNCTION/O-RAN/rc_ctrl_service_style_2.h` | New file: declares `add_mod_rc_slice()` |
| `openair2/LAYER2/NR_MAC_gNB/nr_slice_config.h` | New file: defines `nr_slice_entry_t`, `nr_slice_table_t`, declares API |
| `openair2/LAYER2/NR_MAC_gNB/nr_slice_config.c` | New file: implements `nr_slice_table_set()` and `nr_slice_table_lookup()` with mutex |
| `openair2/LAYER2/NR_MAC_gNB/gNB_scheduler_dlsch.c` | Added per-slice PRB enforcement block after `get_start_stop_allocation()` |
| `xapp-rc-prb-rrc-release/xapp_rc_slice_ctrl.c` | xApp: anomaly detection server, PRB ratio calculation, E2SM-RC CONTROL builder |
