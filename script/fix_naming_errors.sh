#!/bin/bash
# Fix BIDS naming errors - ses-02 files incorrectly named with ses-01

set -e

BIDS_DIR="/Volumes/Work/Work/long/bids"

echo "========================================"
echo "BIDS Naming Error Fixer"
echo "========================================"
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Find all naming errors
echo "Scanning for naming errors..."
echo ""

errors_found=0

# Check for ses-02 directories with ses-01 filenames
while IFS= read -r file; do
    if [ -n "$file" ]; then
        errors_found=$((errors_found + 1))
        dir=$(dirname "$file")
        basename=$(basename "$file")
        # Fix: replace ses-01 with ses-02 in filename
        new_basename=$(echo "$basename" | sed 's/ses-01/ses-02/')
        new_file="${dir}/${new_basename}"

        echo -e "${YELLOW}ERROR FOUND:${NC}"
        echo "  Location: $file"
        echo "  Should be: $new_file"
        echo ""
    fi
done < <(find "$BIDS_DIR" -path "*/ses-02/func/*ses-01*" -o -path "*/ses-02/anat/*ses-01*" -o -path "*/ses-02/fmap/*ses-01*" 2>/dev/null)

# Check for ses-01 directories with ses-02 filenames
while IFS= read -r file; do
    if [ -n "$file" ]; then
        errors_found=$((errors_found + 1))
        dir=$(dirname "$file")
        basename=$(basename "$file")
        # Fix: replace ses-02 with ses-01 in filename
        new_basename=$(echo "$basename" | sed 's/ses-02/ses-01/')
        new_file="${dir}/${new_basename}"

        echo -e "${YELLOW}ERROR FOUND:${NC}"
        echo "  Location: $file"
        echo "  Should be: $new_file"
        echo ""
    fi
done < <(find "$BIDS_DIR" -path "*/ses-01/func/*ses-02*" -o -path "*/ses-01/anat/*ses-02*" -o -path "*/ses-01/fmap/*ses-02*" 2>/dev/null)

if [ $errors_found -eq 0 ]; then
    echo -e "${GREEN}✓ No naming errors found!${NC}"
    exit 0
fi

echo "========================================"
echo -e "${RED}Found $errors_found naming errors${NC}"
echo "========================================"
echo ""
echo "Fix these errors? (y/n)"
read -r response

if [[ ! "$response" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Fixing errors..."
echo ""

fixed=0

# Fix ses-02 directories with ses-01 filenames
while IFS= read -r file; do
    if [ -n "$file" ]; then
        dir=$(dirname "$file")
        basename=$(basename "$file")
        new_basename=$(echo "$basename" | sed 's/ses-01/ses-02/')
        new_file="${dir}/${new_basename}"

        echo -e "${GREEN}Renaming:${NC}"
        echo "  From: $basename"
        echo "  To:   $new_basename"

        mv "$file" "$new_file"
        fixed=$((fixed + 1))
    fi
done < <(find "$BIDS_DIR" -path "*/ses-02/func/*ses-01*" -o -path "*/ses-02/anat/*ses-01*" -o -path "*/ses-02/fmap/*ses-01*" 2>/dev/null)

# Fix ses-01 directories with ses-02 filenames
while IFS= read -r file; do
    if [ -n "$file" ]; then
        dir=$(dirname "$file")
        basename=$(basename "$file")
        new_basename=$(echo "$basename" | sed 's/ses-02/ses-01/')
        new_file="${dir}/${new_basename}"

        echo -e "${GREEN}Renaming:${NC}"
        echo "  From: $basename"
        echo "  To:   $new_basename"

        mv "$file" "$new_file"
        fixed=$((fixed + 1))
    fi
done < <(find "$BIDS_DIR" -path "*/ses-01/func/*ses-02*" -o -path "*/ses-01/anat/*ses-02*" -o -path "*/ses-01/fmap/*ses-02*" 2>/dev/null)

echo ""
echo "========================================"
echo -e "${GREEN}✓ Fixed $fixed files${NC}"
echo "========================================"
echo ""
echo "Verifying fix..."
remaining=$(find "$BIDS_DIR" \( -path "*/ses-02/func/*ses-01*" -o -path "*/ses-02/anat/*ses-01*" -o -path "*/ses-02/fmap/*ses-01*" -o -path "*/ses-01/func/*ses-02*" -o -path "*/ses-01/anat/*ses-02*" -o -path "*/ses-01/fmap/*ses-02*" \) 2>/dev/null | wc -l | tr -d ' ')

if [ "$remaining" -eq 0 ]; then
    echo -e "${GREEN}✓ All naming errors fixed!${NC}"
else
    echo -e "${RED}⚠ Warning: $remaining errors still remain${NC}"
fi
