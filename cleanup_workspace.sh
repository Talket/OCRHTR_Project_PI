#!/bin/bash
echo "🧹 Cleaning up OCRHTR Project workspace..."

# Create clean directories
mkdir -p tests corpus

# Move testing files safely out of the production root
mv test_*.py validate_corpus.py tests/ 2>/dev/null

# Move all sample documents into the corpus folder
mv *.pdf *.jpg corpus/ 2>/dev/null

# Delete all diagnostic/temporary scripts
rm -f debug_*.py generate_final_json.py inspect_quality.py preprocess.py

# Delete all temporary images and JSON outputs
rm -f *.png *.json

# Delete random test text files (keeping english_vocabulary.txt and requirements.txt)
rm -f output*.txt

echo "✅ Workspace cleaned. Only core production files remain."
ls -lh
