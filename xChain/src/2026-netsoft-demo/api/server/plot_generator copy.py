import pandas as pd
import matplotlib.pyplot as plt

def load_csv(filepath):
    """Load a CSV file and compute elapsed seconds from the first timestamp."""
    df = pd.read_csv(filepath, parse_dates=["timestamp"])
    # Calculate elapsed seconds from the first timestamp
    df["elapsed_seconds"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()
    return df

def generate_charts(csv_file_1, csv_file_2, label_1="Model 1", label_2="Model 2"):
    """Plot latency from two CSV files aligned by elapsed seconds, trimmed to shortest duration."""

    # Load data
    df1 = load_csv(csv_file_1)
    df2 = load_csv(csv_file_2)

    # Find the shortest duration
    max_seconds = min(df1["elapsed_seconds"].iloc[-1], df2["elapsed_seconds"].iloc[-1])

    # Trim both dataframes to the shortest duration
    df1 = df1[df1["elapsed_seconds"] <= max_seconds]
    df2 = df2[df2["elapsed_seconds"] <= max_seconds]

    # Create the figure and axis
    fig, ax = plt.subplots(figsize=(14, 6))

    # Plot each model's latency using elapsed seconds with thicker lines
    ax.plot(df1["elapsed_seconds"], df1["latency_ms"], label=label_1, linewidth=3, color="#76c893")
    ax.plot(df2["elapsed_seconds"], df2["latency_ms"], label=label_2, linewidth=3, color="#fb8500")

    # Labels, title, legend, grid
    ax.set_xlabel("Elapsed Time (seconds)", fontsize=12)
    ax.set_ylabel("Latency (ms)", fontsize=12)
    # ax.set_title("ML Model Latency Comparison", fontsize=14)
    ax.legend(fontsize=11)
    ax.grid(True, linestyle="--", alpha=0.6)

    # Ensure x-axis uses integer ticks
    ax.xaxis.set_major_locator(plt.MaxNLocator(integer=True))

    plt.tight_layout()
    plt.savefig("latency_comparison.png", dpi=150)
    plt.show()

    print("Plot saved as 'latency_comparison.png'")

if __name__ == "__main__":
    # ----- CONFIGURE THESE -----
    CSV_FILE_1 = "data/fastinfer/vr/latency.csv"   # path to first CSV file
    CSV_FILE_2 = "data/cnn/vr/latency.csv"   # path to second CSV file
    LABEL_1 = "FastInfer"                  # legend label for first model
    LABEL_2 = "CNN"                  # legend label for second model
    # ---------------------------

    generate_charts(CSV_FILE_1, CSV_FILE_2, LABEL_1, LABEL_2)
