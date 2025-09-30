# Enabling Reusable and Comparable xApps in the Machine Learning-Driven Open RAN

This repository contains the supplementary materials to the paper _Enabling Reeusable and Comparable xApps in the Machine Learning-Driven Open-RAN_ by Juan Luis Herrera, Sofia Montebugnoli, Paolo Bellavista and Luca Foschini.

Concretely, the repository offers the Machine Learning (ML) models used throughout the evaluation and the dataset they were trained on.

## Repository structure

- `models`: Machine learning models sorted by the metric they predict. Within the subdirectories, you find
    - `Model-{Model Type}-{Metric}.pkl`: Trained model of type `{Model Type}` to predict metric `{Metric}`. All models are provided in Python Pickle format and provide a single object with a `scikit-learn`-compatible interface.
    - `ModelDescriptor.json`: Model descriptor for the predicted metric. As all model types have the same interface, the same descriptor can be used across different model types for the same metric.
- `Dataset.csv`: Original dataset used to train the ML models, extracted from the measurements the DUs of simulates ns-O-RAN scenarios.
- `README.md`: This documentation.
- Paper: 10.1109/HPSR62440.2024.10635962