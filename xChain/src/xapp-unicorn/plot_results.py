"""
Collect RESULT lines from agent pods and plot accuracy over time.

Usage:
  # 1. Collect logs (run during or after the experiment)
  python plot_results.py collect --duration 120   # streams for 120s then stops
  # or dump existing logs:
  python plot_results.py collect --from-existing

  # 2. Plot
  python plot_results.py plot --baseline logs/baseline.jsonl --agent logs/agent.jsonl
"""
import argparse, json, subprocess, time, threading
from pathlib import Path

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

PREPROC_POD       = "deployment/tractor-mono"
PREPROC_CTR       = "agent"
FILTER_POD        = "deployment/xchain-unicorn"
FILTER_CTR        = "agent"
GROUND_TRUTH      = "URLLC"   # kpm-sim replays URLLC data → correct TRACTOR label
GROUND_TRUTH_APP  = "Teams"   # expected UNICORN application (matches kpm-sim CSV)


# ── Collection ────────────────────────────────────────────────────────────────

def _stream_result_lines(pod, container, out_file, stop_event):
    """kubectl logs -f, write RESULT lines as JSONL."""
    cmd = ["kubectl", "logs", "-f", pod, "-c", container]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    with open(out_file, "w") as f:
        for line in proc.stdout:
            if stop_event.is_set():
                proc.terminate()
                break
            if line.startswith("RESULT "):
                f.write(line[len("RESULT "):].strip() + "\n")
                f.flush()


def collect(label: str, duration: int):
    out_preproc = LOGS_DIR / f"{label}_preproc.jsonl"
    out_filter  = LOGS_DIR / f"{label}_filter.jsonl"
    stop = threading.Event()

    t1 = threading.Thread(target=_stream_result_lines,
                          args=(PREPROC_POD, PREPROC_CTR, out_preproc, stop), daemon=True)
    t2 = threading.Thread(target=_stream_result_lines,
                          args=(FILTER_POD,  FILTER_CTR,  out_filter,  stop), daemon=True)
    t1.start(); t2.start()

    print(f"Collecting '{label}' logs for {duration}s  (Ctrl-C to stop early)...")
    try:
        time.sleep(duration)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    t1.join(timeout=3); t2.join(timeout=3)
    print(f"Saved → {out_preproc}  {out_filter}")


# ── Parsing ───────────────────────────────────────────────────────────────────

def load_events(preproc_jsonl: Path, filter_jsonl: Path):
    events = []
    for path in [preproc_jsonl, filter_jsonl]:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    events.sort(key=lambda e: e.get("t", 0))
    return events


def _rolling(times, labels, window_sec):
    """Shared rolling-window accuracy computation."""
    acc = []
    for t in times:
        window = [labels[j] for j, tw in enumerate(times) if t - window_sec <= tw <= t]
        acc.append(sum(window) / len(window))
    return acc


def rolling_accuracy(events, window_sec=10.0, ground_truth=GROUND_TRUTH):
    """Rolling accuracy of TRACTOR classification (traffic_type == ground_truth)."""
    preds = [(e["t"], int(e["traffic_type"] == ground_truth))
             for e in events if e.get("event") == "tractor_predict"]
    if not preds:
        return [], []
    t0     = preds[0][0]
    times  = [p[0] - t0 for p in preds]
    labels = [p[1]       for p in preds]
    return times, _rolling(times, labels, window_sec)


def rolling_unicorn_accuracy(events, window_sec=10.0, ground_truth_app=GROUND_TRUTH_APP,
                              grid_sec=1.0):
    """
    Rolling accuracy of UNICORN application classification on a fixed time grid.
    Correct = application field == ground_truth_app.
    Only unicorn_predict events are counted (rows that passed TRACTOR filtering).

    Uses a fixed grid (grid_sec resolution) with forward-fill so the line does not
    disappear during TRACTOR window-reset gaps (e.g. after a T switch).
    Returns NaN for leading period before the first prediction arrives.
    """
    import numpy as np

    preds = [(e["t"], int(e.get("application") == ground_truth_app))
             for e in events if e.get("event") == "unicorn_predict"]
    if not preds:
        return [], []

    t0      = preds[0][0]
    t_end   = preds[-1][0] - t0
    times   = [p[0] - t0 for p in preds]
    labels  = [p[1]       for p in preds]

    # Fixed time grid from 0 to t_end
    grid    = np.arange(0, t_end + grid_sec, grid_sec)
    acc_grid = []
    for t in grid:
        window = [labels[j] for j, tw in enumerate(times)
                  if t - window_sec <= tw <= t]
        if window:
            acc_grid.append(sum(window) / len(window))
        else:
            acc_grid.append(float("nan"))   # no data yet — shown as gap

    return grid.tolist(), acc_grid


# ── Plot ──────────────────────────────────────────────────────────────────────

def plot(baseline_prefix: str, agent_prefix: str, out_png: str,
         ground_truth_app: str = GROUND_TRUTH_APP):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    def load(prefix):
        return load_events(LOGS_DIR / f"{prefix}_preproc.jsonl",
                           LOGS_DIR / f"{prefix}_filter.jsonl")

    base_events  = load(baseline_prefix)
    agent_events = load(agent_prefix)

    t_base,  acc_base  = rolling_unicorn_accuracy(base_events,  ground_truth_app=ground_truth_app)
    t_agent, acc_agent = rolling_unicorn_accuracy(agent_events, ground_truth_app=ground_truth_app)

    n_base  = sum(1 for e in base_events  if e.get("event") == "unicorn_predict")
    n_agent = sum(1 for e in agent_events if e.get("event") == "unicorn_predict")
    print(f"UNICORN predictions — baseline: {n_base}  agent: {n_agent}")

    # T switch and complaint events (relative to agent run start)
    t0_agent   = agent_events[0]["t"] if agent_events else 0
    switches   = [(e["t"] - t0_agent, e["old_T"], e["new_T"])
                  for e in agent_events if e.get("event") == "model_switch"]
    complaints = [(e["t"] - t0_agent)
                  for e in agent_events if e.get("event") == "complaint"]

    fig, ax = plt.subplots(figsize=(10, 4.5))

    if t_base and acc_base:
        ax.plot(t_base,  acc_base,  color='#E05252', linewidth=2,
                label=f'No drift detection  (n={n_base})')
    if t_agent and acc_agent:
        ax.plot(t_agent, acc_agent, color='#2D8CFF', linewidth=2,
                label=f'With drift detection  (n={n_agent})')
        if t_base and acc_base:
            import numpy as np
            t_interp = np.array(t_agent)
            a_interp = np.array(acc_agent)
            a_base_i = np.interp(t_interp, t_base, acc_base)
            ax.fill_between(t_interp, a_base_i, a_interp,
                            where=a_interp > a_base_i,
                            alpha=0.12, color='#2D8CFF', label='Accuracy gain')

    for t_c in complaints:
        ax.axvline(t_c, color='purple', linestyle=':', linewidth=1.2, alpha=0.7)

    for i, (t_s, old_T, new_T) in enumerate(switches):
        ax.axvline(t_s, color='darkgreen', linestyle='--', linewidth=1.3, alpha=0.8)
        y_label = 0.96 if i % 2 == 0 else 0.88
        ax.text(t_s + 0.5, y_label, f"T:{old_T}→{new_T}", fontsize=8,
                color='darkgreen', fontweight='bold')

    from matplotlib.lines import Line2D
    extra = [
        Line2D([0],[0], color='purple',    linestyle=':',  linewidth=1.2, label='Complaint'),
        Line2D([0],[0], color='darkgreen', linestyle='--', linewidth=1.3, label='T switch'),
    ]
    handles, labels_ = ax.get_legend_handles_labels()
    ax.legend(handles + extra, labels_ + [h.get_label() for h in extra],
              fontsize=9, loc='lower right')

    ax.set_xlabel("Time (s)", fontsize=12)
    ax.set_ylabel(f"UNICORN Accuracy — app={ground_truth_app} (rolling 10s)", fontsize=11)
    ax.set_title("Effect of xChain Drift Detection on UNICORN Application Accuracy",
                 fontsize=13, fontweight='bold')
    ax.set_ylim(0, 1.05)
    ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_png, dpi=150, bbox_inches='tight')
    print(f"Plot saved → {out_png}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")

    p_col = sub.add_parser("collect")
    p_col.add_argument("--label",    default="agent",
                       help="Name prefix for log files (e.g. 'baseline' or 'agent')")
    p_col.add_argument("--duration", type=int, default=120, help="Seconds to collect")

    p_plot = sub.add_parser("plot")
    p_plot.add_argument("--baseline", default="baseline",        help="Label prefix for baseline logs")
    p_plot.add_argument("--agent",    default="agent",            help="Label prefix for agent logs")
    p_plot.add_argument("--app",      default=GROUND_TRUTH_APP,  help="Ground-truth application name (e.g. Teams)")
    p_plot.add_argument("--out",      default="xchain_accuracy.png")

    args = parser.parse_args()

    if args.cmd == "collect":
        collect(args.label, args.duration)
    elif args.cmd == "plot":
        plot(args.baseline, args.agent, args.out, ground_truth_app=args.app)
    else:
        parser.print_help()
