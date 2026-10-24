#!/bin/bash
set -euo pipefail
cd /opt/aborigen-crm
apt-get update
apt-get install -y tesseract-ocr tesseract-ocr-rus tesseract-ocr-eng
.venv/bin/pip install -r requirements.txt
systemctl restart aborigen-crm
tesseract --list-langs
