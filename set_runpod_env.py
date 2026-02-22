import os

# Set your RunPod API credentials and inference mode for cloud
os.environ["RUNPOD_API_KEY"] = "secret_smileloop_a890ff59417e46058a807c671aa8a17e.T61d334uKa0cqFPYSUBI2zJ1SIEUInzA"
os.environ["RUNPOD_ENDPOINT_ID"] = "<your_runpod_endpoint_id>"  # TODO: Replace with your actual endpoint ID
os.environ["INFERENCE_MODE"] = "cloud"

print("Environment variables for RunPod cloud inference are set.")
