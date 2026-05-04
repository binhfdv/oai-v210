import os
import pandas as pd
import matplotlib.pyplot as plt

FALLBACK_COLORS = ["#8338ec", "#ff006e", "#3a86a7", "#606c38", "#0077b6", "#e63946"]

def load_csv(filepath):
    df = pd.read_csv(filepath, parse_dates=["timestamp"])
    df["elapsed_seconds"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()
    return df

def generate_charts(models, directory, model_colors=None):
    """
    Plot latency from CSV files for each model, aligned by elapsed seconds, trimmed to shortest duration.
    
    Args:
        models (str): Comma-separated model names, e.g. "cnn,fastinfer"
        directory (str): Path to the directory containing the CSV files, 
                         e.g. "./demo/data/vr"
    
    CSV files are expected to follow the pattern: <model>_latency.csv
    For example: cnn_latency.csv, fastinfer_latency.csv
    """
    model_list = [m.strip() for m in models.split(",") if m.strip()]
    colors = model_colors or {}

    if not model_list:
        print("No models provided.")
        return

    _zero_df = pd.DataFrame({"elapsed_seconds": [0], "latency_ms": [0]})

    dataframes = {}
    for model in model_list:
        csv_path = os.path.join(directory, f"{model}_latency.csv")
        try:
            df = load_csv(csv_path)
            if df.empty:
                dataframes[model] = _zero_df
            else:
                dataframes[model] = df
        except Exception:
            dataframes[model] = _zero_df

    max_seconds = min(df["elapsed_seconds"].iloc[-1] for df in dataframes.values())
    for model in dataframes:
        dataframes[model] = dataframes[model][dataframes[model]["elapsed_seconds"] <= max_seconds]

    fig, ax = plt.subplots(figsize=(14, 6))

    fallback_idx = 0
    for model, df in dataframes.items():
        if model in colors:
            color = colors[model]
        else:
            color = FALLBACK_COLORS[fallback_idx % len(FALLBACK_COLORS)]
            fallback_idx += 1
        ax.plot(
            df["elapsed_seconds"],
            df["latency_ms"],
            label=model,
            linewidth=3,
            color=color
        )

    # Labels, legend, grid
    ax.set_xlabel("Elapsed Time (seconds)", fontsize=12)
    ax.set_ylabel("Latency (ms)", fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.6)

    # Ensure x-axis uses integer ticks
    ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))

    plt.tight_layout()

    output_path = os.path.join(directory, "latency_comparison.png")
    plt.savefig(output_path, dpi=150)
    plt.close(fig)

    print(f"Plot saved as '{output_path}'")


if __name__ == "__main__":
    # ----- CONFIGURE THESE -----
    MODELS = "cnn,fastinfer"
    DIRECTORY = "data/vr"
    # ---------------------------

    generate_charts(MODELS, DIRECTORY)
