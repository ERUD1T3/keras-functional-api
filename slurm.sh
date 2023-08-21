#!/bin/bash

#SBATCH --job-name=TestJob            # Job name
#SBATCH --nodes=1                     # Number of nodes
#SBATCH --ntasks=1                    # Number of tasks
#SBATCH --mem=50MB                    # Memory per node
#SBATCH --time=00:15:00               # Time limit (15 minutes)
#SBATCH --partition=gpu               # GPU partition
#SBATCH --gres=gpu:1                  # Number of GPUs per node
#SBATCH --output=testjob.%J.out       # Output file
#SBATCH --error=testjob.%J.err        # Error file

echo "Starting at date $(date)"

echo "Running on hosts: $SLURM_NODELIST"

echo "Running on $SLURM_NNODES nodes."

echo "Running on $SLURM_NPROCS processors."

echo "Current working directory is $(pwd)"

srun python3 /path/to/your/my_script.py # Run your Python script