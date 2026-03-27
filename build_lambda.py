import os
import zipfile

def create_lambda_zip():
    output_zip = 'deployment_package.zip'
    source_files = ['lambda_function.py']
    source_dirs = ['package']

    print(f"📦 Creating {output_zip}...")
    
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add main files
        for file in source_files:
            if os.path.exists(file):
                print(f"  Adding file: {file}")
                zipf.write(file)
            else:
                print(f"  ⚠️ Warning: {file} not found!")

        # Add package directory recursively
        for s_dir in source_dirs:
            if os.path.exists(s_dir):
                print(f"  Adding directory: {s_dir}/")
                for root, dirs, files in os.walk(s_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        # Avoid adding __pycache__
                        if '__pycache__' not in file_path:
                            zipf.write(file_path)
            else:
                print(f"  ⚠️ Warning: {s_dir} directory not found!")
    
    print(f"✅ Success! File size: {os.path.getsize(output_zip) / (1024*1024):.2f} MB")
    print("🚀 You can now upload 'deployment_package.zip' to AWS Lambda.")

if __name__ == "__main__":
    create_lambda_zip()
