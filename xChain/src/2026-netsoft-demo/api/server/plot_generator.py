import os
import pandas as pd
import matplotlib.pyplot as plt

# Model foreground colors matching the frontend AI model configs
MODEL_COLORS = {
    "fastinfer": "#76c893",
    "cnn": "#fb8500",
    "gnn": "#dd2d4a",
    "transformer": "#33658a",
}

# Fallback palette for any model not explicitly mapped above
FALLBACK_COLORS = ["#8338ec", "#ff006e", "#3a86a7", "#606c38", "#0077b6", "#e63946"]

def load_csv(filepath):
    """Load a CSV file and compute elapsed seconds from the first timestamp."""
    df = pd.read_csv(filepath, parse_dates=["timestamp"])
    # Calculate elapsed seconds from the first timestamp
    df["elapsed_seconds"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()
    return df

def get_model_color(model, fallback_index):
    """Return the configured color for a model, or a fallback color if not found."""
    if model in MODEL_COLORS:
        return MODEL_COLORS[model]
    return FALLBACK_COLORS[fallback_index % len(FALLBACK_COLORS)]

def generate_charts(models, directory):
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

    if not model_list:
        print("No models provided.")
        return

    # Load all dataframes
    dataframes = {}
    for model in model_list:
        csv_path = os.path.join(directory, f"{model}_latency.csv")
        if not os.path.exists(csv_path):
            print(f"Warning: CSV file not found for model '{model}': {csv_path}")
            continue
        try:
            df = load_csv(csv_path)
            dataframes[model] = df
        except Exception as e:
            print(f"Error loading CSV for model '{model}': {e}")
            continue

    if not dataframes:
        print("No valid CSV files found. Skipping chart generation.")
        return

    # Find the shortest duration across all loaded dataframes
    max_seconds = min(df["elapsed_seconds"].iloc[-1] for df in dataframes.values())

    # Trim all dataframes to the shortest duration
    for model in dataframes:
        dataframes[model] = dataframes[model][dataframes[model]["elapsed_seconds"] <= max_seconds]

    # Create the figure and axis
    fig, ax = plt.subplots(figsize=(14, 6))

    # Plot each model's latency with its matching foreground color
    fallback_idx = 0
    for model, df in dataframes.items():
        color = get_model_color(model, fallback_idx)
        if model not in MODEL_COLORS:
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
