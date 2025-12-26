import zipfile
import os
import sys

def zip_project():
    source_dir = os.getcwd()
    output_filename = "deployment_package.zip"
    
    print(f"Zipping {source_dir} to {output_filename}...")
    
    # Files/Dirs to exclude
    exclude_dirs = {'.git', '__pycache__', 'logs', 'venv', '.idea', '.vscode'}
    exclude_files = {output_filename, 'deploy.ps1', 'deploy.sh', '.ds_store', 'signals.db', '.env'}
    
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            # Modify dirs in-place to skip excluded
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file.lower() in exclude_files:
                    continue
                if file.endswith('.zip') or file.endswith('.key'):
                    continue
                    
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                zipf.write(file_path, arcname)
                
    print(f"Created {output_filename}, size: {os.path.getsize(output_filename) / 1024:.2f} KB")

if __name__ == "__main__":
    zip_project()
