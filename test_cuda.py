import torch
import time
import sys

def test_gpu():
    print(f"Python version: {sys.version}")
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    
    if torch.cuda.is_available():
        print(f"CUDA version: {torch.version.cuda}")
        print(f"CUDA device count: {torch.cuda.device_count()}")
        print(f"Current CUDA device: {torch.cuda.current_device()}")
        print(f"CUDA device name: {torch.cuda.get_device_name(0)}")
        
        # Test GPU computation
        print("\nTesting GPU computation performance...")
        
        # Create a large tensor on CPU
        size = 5000
        cpu_start = time.time()
        x_cpu = torch.randn(size, size)
        y_cpu = torch.randn(size, size)
        z_cpu = torch.matmul(x_cpu, y_cpu)
        cpu_time = time.time() - cpu_start
        print(f"CPU matrix multiplication time: {cpu_time:.4f} seconds")
        
        # Create a large tensor on GPU
        gpu_start = time.time()
        x_gpu = torch.randn(size, size, device="cuda")
        y_gpu = torch.randn(size, size, device="cuda")
        z_gpu = torch.matmul(x_gpu, y_gpu)
        # Force synchronization to measure accurate time
        torch.cuda.synchronize()
        gpu_time = time.time() - gpu_start
        print(f"GPU matrix multiplication time: {gpu_time:.4f} seconds")
        print(f"GPU speedup: {cpu_time/gpu_time:.2f}x faster")
    else:
        print("No CUDA devices available. Using CPU only.")
        print("To use GPU, please install a CUDA-compatible PyTorch version.")
        print("Run: pip install torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0 --force-reinstall")
        
if __name__ == "__main__":
    test_gpu() 