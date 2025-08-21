# Care AI - Prompt Management System

This document describes the new prompt management system that separates all AI prompts into external files for better maintainability.

## 📁 Directory Structure

```
care_ai_rohit13/
├── app_new.py              # Main application file
├── prompt_loader.py        # Prompt loading utility
├── prompts/                # Directory containing all prompt files
│   ├── medical_assistant_system.txt
│   ├── emr_analysis.txt
│   ├── emr_system.txt
│   ├── aadhaar_analysis.txt
│   ├── aadhaar_system.txt
│   ├── pdf_ocr_analysis.txt
│   ├── pdf_ocr_system.txt
│   ├── insurance_ocr_analysis.txt
│   ├── insurance_ocr_system.txt
│   ├── photo_tongue_analysis.txt
│   ├── photo_throat_analysis.txt
│   ├── photo_infection_analysis.txt
│   ├── photo_laboratory_analysis.txt
│   ├── photo_medical_image_analysis.txt
│   ├── photo_signal_analysis.txt
│   ├── photo_analysis_system.txt
│   ├── diagnostic_tests_system.txt
│   ├── differential_question_system.txt
│   ├── answer_processing_system.txt
│   ├── icd11_generation_system.txt
│   ├── icd10_diagnosis_system.txt
│   ├── clinical_summary_system.txt
│   ├── dynamic_questions_system.txt
│   └── followup_questions_system.txt
├── test_prompts.py         # Testing script for prompt loading
└── convert_prompts.py      # Conversion script (run once)
```

## 🚀 Implementation Steps

### Step 1: Test Current Setup
```bash
python test_prompts.py
```
This will verify all prompt files are correctly created and accessible.

### Step 2: Convert Your Application (Optional - Automated)
```bash
python convert_prompts.py
```
This will automatically replace all hardcoded prompts in `app_new.py` with calls to external prompt files.

**Note**: A backup file `app_new_backup.py` will be created automatically.

### Step 3: Manual Implementation (Alternative)
If you prefer manual implementation, follow this pattern:

#### Before (Hardcoded):
```python
system_prompt = """You are an expert medical AI assistant with comprehensive knowledge of:
- Clinical medicine and diagnostics
- Patient assessment and medical history taking
..."""
```

#### After (External File):
```python
system_prompt = load_prompt("medical_assistant_system")
```

## 📚 Usage Examples

### Basic Prompt Loading
```python
from prompt_loader import load_prompt

# Load a system prompt
system_prompt = load_prompt("medical_assistant_system")

# Load an analysis prompt
analysis_prompt = load_prompt("emr_analysis")
```

### Photo Analysis Prompts
```python
from prompt_loader import get_photo_analysis_prompt

# Get tongue analysis prompt
tongue_prompt = get_photo_analysis_prompt("tongue")

# Get medical imaging prompt with report type
imaging_prompt = get_photo_analysis_prompt("medical_image", report_type="CT_SCAN")
```

### List Available Prompts
```python
from prompt_loader import list_available_prompts

available = list_available_prompts()
print(f"Available prompts: {available}")
```

## ✅ Benefits

1. **Maintainability**: Easy to edit prompts without touching code
2. **Version Control**: Track prompt changes separately from code changes
3. **Collaboration**: Non-developers can edit prompts safely
4. **Testing**: Easier A/B testing of different prompt variations
5. **Organization**: Clear separation of concerns
6. **Reusability**: Prompts can be shared across different parts of the application

## 🔧 Adding New Prompts

1. Create a new `.txt` file in the `prompts/` directory
2. Add your prompt content to the file
3. Use `load_prompt("your_new_prompt_name")` in your code

## 🛡️ Error Handling

The prompt loader includes built-in error handling:
- File not found errors are caught and reported
- Empty files are detected
- Encoding issues are handled gracefully
- Fallback mechanisms for critical prompts

## 📝 File Naming Convention

- Use descriptive names: `medical_assistant_system.txt`
- Use underscores for spaces: `photo_tongue_analysis.txt`
- Include the prompt type: `*_system.txt` for system prompts, `*_analysis.txt` for analysis prompts
- Keep names concise but clear

## 🔄 Maintenance

To update prompts:
1. Edit the appropriate `.txt` file in the `prompts/` directory
2. No need to restart the application (prompts are loaded on each request)
3. Test changes immediately

## 🧪 Testing

Run the test script periodically to ensure all prompts are accessible:
```bash
python test_prompts.py
```

This will verify:
- All prompt files exist and are readable
- Content is not empty or corrupted
- Special prompt functions work correctly
- Overall system health
