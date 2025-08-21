from flask import Flask, render_template, request, jsonify, session, redirect
from openai import OpenAI
import json
import base64
from datetime import datetime
import os
import tempfile
import uuid
from dotenv import load_dotenv
from prompt_loader import load_prompt, get_photo_analysis_prompt

# Load environment variables
load_dotenv()

# Debug: Check what API key is loaded
api_key_from_env = os.getenv('OPENAI_API_KEY')
print(f"DEBUG: API key from .env: {api_key_from_env[:15] if api_key_from_env else 'None'}...")

app = Flask(__name__)
app.secret_key = 'your-secure-secret-key-2024'  # Change this to a secure secret key

# Configure OpenAI client
openai_client = OpenAI(api_key=api_key_from_env)

# File storage functions for patient data
APP_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'care_app_data')
os.makedirs(APP_DATA_DIR, exist_ok=True)

def get_session_file_path():
    """Get the file path for storing session data"""
    session_id = session.get('session_id')
    if not session_id:
        session_id = str(uuid.uuid4())
        session['session_id'] = session_id
    return os.path.join(APP_DATA_DIR, f'patient_data_{session_id}.json')

def save_patient_data(patient_data):
    """Save patient data to temporary file"""
    try:
        file_path = get_session_file_path()
        with open(file_path, 'w') as f:
            json.dump(patient_data, f, indent=2)
        print(f"DEBUG: Saved patient data to {file_path}")
        return True
    except Exception as e:
        print(f"ERROR: Failed to save patient data: {str(e)}")
        return False

def load_patient_data():
    """Load patient data from temporary file"""
    try:
        file_path = get_session_file_path()
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                data = json.load(f)
            print(f"DEBUG: Loaded patient data from {file_path}")
            return data
        else:
            print(f"DEBUG: No patient data file found at {file_path}")
            return {}
    except Exception as e:
        print(f"ERROR: Failed to load patient data: {str(e)}")
        return {}

def clear_patient_data():
    """Clear patient data file"""
    try:
        file_path = get_session_file_path()
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"DEBUG: Cleared patient data file {file_path}")
        return True
    except Exception as e:
        print(f"ERROR: Failed to clear patient data: {str(e)}")
        return False

def clear_all_patient_data():
    """Clear all patient data files from the care_app_data folder"""
    try:
        import glob
        # Find all patient data files
        pattern = os.path.join(APP_DATA_DIR, 'patient_data_*.json')
        files = glob.glob(pattern)
        
        cleared_count = 0
        for file_path in files:
            try:
                os.remove(file_path)
                print(f"DEBUG: Removed file {file_path}")
                cleared_count += 1
            except Exception as e:
                print(f"ERROR: Failed to remove file {file_path}: {str(e)}")
        
        print(f"✅ Cleared {cleared_count} patient data files from care_app_data folder")
        return True
        
    except Exception as e:
        print(f"❌ ERROR: Failed to clear all patient data: {str(e)}")
        return False

# Error handlers for AJAX requests
@app.errorhandler(404)
def not_found_error(error):
    # Handle favicon requests and other 404s gracefully
    if request.path == '/favicon.ico':
        return '', 204  # No content response for favicon
    if request.is_json or request.path.startswith('/save') or request.path.startswith('/generate'):
        return jsonify({'success': False, 'error': 'Endpoint not found'}), 404
    return redirect('/')  # Redirect to home page instead of using missing 404.html

@app.errorhandler(500)
def internal_error(error):
    if request.is_json or request.path.startswith('/save') or request.path.startswith('/generate'):
        return jsonify({'success': False, 'error': 'Internal server error'}), 500
    return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.errorhandler(Exception)
def handle_exception(e):
    if request.is_json or request.path.startswith('/save') or request.path.startswith('/generate'):
        return jsonify({'success': False, 'error': str(e)}), 500
    # For non-AJAX requests, let Flask handle it normally
    raise e

def initialize_session():
    """Initialize comprehensive medical session"""
    try:
        if 'patient_data' not in session:
            print("Initializing new patient session")
            session['patient_data'] = {
                'case_category': {},         # Step 1: Case category (accident/illness)
                'registration': {},          # Step 2: Patient registration
                'vitals': {},               # Step 3: Vital signs
                'follow_up_questions': {},  # Step 4: Removed - was LLM-generated follow-up
                'complaints': {},           # Step 5: Open-ended complaints
                'complaint_analysis': {},   # Step 6: LLM complaint analysis
                'diagnosis': {},            # Step 7: Final ICD diagnosis
                'session_id': datetime.now().isoformat(),
                'step_completed': 0,
                'created_at': datetime.now().isoformat(),
                'data_timestamps': {},       # Track when each step's data was last modified
                'llm_timestamps': {}         # Track when LLM responses were generated
            }
        else:
            print("Using existing patient session")
    except Exception as e:
        print(f"Error in initialize_session: {str(e)}")
        session['patient_data'] = {
            'registration': {},
            'vitals': {},
            'follow_up_questions': {},
            'complaints': {},
            'complaint_analysis': {},
            'diagnosis': {},
            'session_id': datetime.now().isoformat(),
            'step_completed': 0,
            'created_at': datetime.now().isoformat(),
            'data_timestamps': {},
            'llm_timestamps': {}
        }

def validate_session_step(required_step):
    """Validate if user has completed required steps using file storage"""
    try:
        print(f"DEBUG: Validating session for required step {required_step}")
        patient_data = load_patient_data()
        if not patient_data:
            print(f"ERROR: Session validation failed: no patient data found")
            print(f"DEBUG: Session ID: {session.get('session_id', 'No session ID')}")
            return False
        
        current_step = patient_data.get('step_completed', 0)
        result = current_step >= required_step
        print(f"DEBUG: Session validation for step {required_step}: {result} (current step: {current_step})")
        print(f"DEBUG: Patient data keys: {list(patient_data.keys())}")
        return result
    except Exception as e:
        print(f"ERROR: Error in validate_session_step: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def needs_llm_regeneration(step_number):
    """Check if LLM regeneration is needed based on data changes"""
    if 'patient_data' not in session:
        return True
    
    data_timestamps = session['patient_data'].get('data_timestamps', {})
    llm_timestamps = session['patient_data'].get('llm_timestamps', {})
    
    # Always regenerate if no LLM response exists for this step
    if step_number not in llm_timestamps:
        return True
    
    llm_time = llm_timestamps.get(step_number)
    
    # Check if any prerequisite step data has changed since LLM response was generated
    prerequisite_steps = {
        4: [1, 2, 3],        # Step 4: REMOVED - was depend on case category, registration and vitals
        5: [1, 2, 3, 4],     # Step 5 depends on case category, registration, vitals, and follow-up
        6: [1, 2, 3, 4, 5],  # Step 6 depends on all previous steps
        7: [1, 2, 3, 4, 5, 6] # Step 7 depends on all previous steps
    }
    
    for prereq_step in prerequisite_steps.get(step_number, []):
        if prereq_step in data_timestamps:
            data_time = data_timestamps[prereq_step]
            if data_time > llm_time:
                print(f"LLM regeneration needed for step {step_number}: prerequisite step {prereq_step} data changed")
                return True
    
    return False

def update_data_timestamp(step_number):
    """Update timestamp when step data is modified using file storage"""
    try:
        patient_data = load_patient_data()
        if not patient_data:
            patient_data = {'created_at': datetime.now().isoformat()}
        
        if 'data_timestamps' not in patient_data:
            patient_data['data_timestamps'] = {}
        
        # Ensure step_number is always stored as string for JSON serialization
        patient_data['data_timestamps'][str(step_number)] = datetime.now().isoformat()
        save_patient_data(patient_data)
        print(f"Updated data timestamp for step {step_number}")
    except Exception as e:
        print(f"Error updating data timestamp for step {step_number}: {str(e)}")

def update_llm_timestamp(step_number):
    """Update timestamp when LLM response is generated using file storage"""
    try:
        patient_data = load_patient_data()
        if not patient_data:
            patient_data = {'created_at': datetime.now().isoformat()}
        
        if 'llm_timestamps' not in patient_data:
            patient_data['llm_timestamps'] = {}
        
        # Ensure step_number is always stored as string for JSON serialization
        patient_data['llm_timestamps'][str(step_number)] = datetime.now().isoformat()
        save_patient_data(patient_data)
        print(f"Updated LLM timestamp for step {step_number}")
    except Exception as e:
        print(f"Error updating LLM timestamp for step {step_number}: {str(e)}")

def call_gpt4(prompt, context_data=None):
    """Call GPT-4 API with medical expertise"""
    try:
        # Load system prompt from external file
        system_prompt = load_prompt("medical_assistant_system")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        
        if context_data:
            context_text = f"Patient Context: {json.dumps(context_data, indent=2)}"
            messages.append({"role": "user", "content": context_text})
        
        # Set the API key if not already set
        # Get API key
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            print("WARNING: OpenAI API key not found. Please set OPENAI_API_KEY environment variable.")
            raise Exception("OpenAI API key not found. Please set OPENAI_API_KEY environment variable.")
        
        print(f"DEBUG: Using API key: {api_key[:15]}...{api_key[-4:]}")
        print(f"Making API call to GPT-4 with {len(messages)} messages")
        
        # Create a fresh OpenAI client to ensure we're using the correct API key
        from openai import OpenAI
        fresh_client = OpenAI(api_key=api_key)
        
        # Use the new OpenAI API format (v1.0.0+)
        response = fresh_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=2000,
            temperature=0.3
        )
        
        result = response.choices[0].message.content
        print(f"GPT-4 response received successfully: {len(result)} characters")
        return result
        
    except Exception as e:
        print(f"Error calling GPT-4: {str(e)}")
        raise e

def calculate_bmi(height, weight, height_unit='cm', weight_unit='kg'):
    """Calculate BMI from height and weight"""
    try:
        height_val = float(height)
        weight_val = float(weight)
        
        # Convert to metric if needed
        if height_unit == 'inches':
            height_val = height_val * 2.54
        if weight_unit == 'lbs':
            weight_val = weight_val * 0.453592
            
        # Calculate BMI
        height_m = height_val / 100
        bmi = weight_val / (height_m ** 2)
        return round(bmi, 1)
    except:
        return None

def generate_fallback_analysis(patient_data):
    """Generate fallback analysis when GPT-4 fails"""
    complaint_text = ""
    if patient_data.get('complaints'):
        complaint_text = patient_data['complaints'].get('raw_text', '')
    
    # Extract basic labels from complaint text
    basic_labels = []
    common_symptoms = ['pain', 'fever', 'headache', 'nausea', 'vomiting', 'fatigue', 'dizziness', 'cough', 'chest pain', 'abdominal pain']
    
    for symptom in common_symptoms:
        if symptom.lower() in complaint_text.lower():
            basic_labels.append({
                "label": symptom.capitalize(),
                "primary": symptom in ['pain', 'fever', 'headache'],
                "extracted_from": "Patient complaint text",
                "clinical_significance": f"{symptom.capitalize()} requires clinical evaluation"
            })
    
    if not basic_labels:
        basic_labels.append({
            "label": "General symptoms",
            "primary": True,
            "extracted_from": "Patient complaint text",
            "clinical_significance": "Patient-reported symptoms require medical assessment"
        })
    
    # Generate questions with proper radio button options
    questions = []
    for i, label in enumerate(basic_labels[:8]):  # Limit to 8 questions
        if 'pain' in label['label'].lower():
            questions.append({
                "question": f"How would you describe the intensity of your {label['label'].lower()}?",
                "purpose": "Assess pain severity for clinical evaluation",
                "category": "symptom_analysis",
                "options": [
                    {"value": "mild", "text": "Mild (1-3 out of 10)", "clinical_significance": "Low intensity pain"},
                    {"value": "moderate", "text": "Moderate (4-6 out of 10)", "clinical_significance": "Moderate pain affecting daily activities"},
                    {"value": "severe", "text": "Severe (7-8 out of 10)", "clinical_significance": "High intensity pain requiring attention"},
                    {"value": "extreme", "text": "Extreme (9-10 out of 10)", "clinical_significance": "Severe pain requiring immediate care"}
                ]
            })
        elif 'fever' in label['label'].lower():
            questions.append({
                "question": "How long have you had fever symptoms?",
                "purpose": "Determine fever duration for diagnosis",
                "category": "symptom_analysis",
                "options": [
                    {"value": "hours", "text": "A few hours", "clinical_significance": "Acute onset fever"},
                    {"value": "1-2days", "text": "1-2 days", "clinical_significance": "Recent onset fever"},
                    {"value": "3-7days", "text": "3-7 days", "clinical_significance": "Ongoing fever requiring evaluation"},
                    {"value": "week_plus", "text": "More than a week", "clinical_significance": "Prolonged fever needs investigation"}
                ]
            })
        else:
            questions.append({
                "question": f"How often do you experience {label['label'].lower()}?",
                "purpose": "Assess symptom frequency",
                "category": "symptom_analysis",
                "options": [
                    {"value": "constant", "text": "Constantly", "clinical_significance": "Persistent symptom"},
                    {"value": "frequent", "text": "Several times a day", "clinical_significance": "Frequent occurrence"},
                    {"value": "occasional", "text": "Occasionally", "clinical_significance": "Intermittent symptom"},
                    {"value": "rare", "text": "Rarely", "clinical_significance": "Infrequent occurrence"}
                ]
            })
    
    return {
        "complaint_labels": basic_labels,
        "features_for_labels": [
            {
                "label": label["label"],
                "features": [
                    {
                        "feature": "Presence",
                        "value": "Present",
                        "clinical_relevance": "Patient reports this symptom"
                    },
                    {
                        "feature": "Severity",
                        "value": "To be determined",
                        "clinical_relevance": "Severity assessment needed"
                    }
                ]
            } for label in basic_labels
        ],
        "feature_label_matrix": [
            {
                "feature": "Patient-reported symptoms",
                "associated_labels": [label["label"] for label in basic_labels],
                "strength": "moderate",
                "diagnostic_value": "Self-reported symptoms provide initial assessment direction"
            }
        ],
        "correlated_labels": [
            {
                "primary_label": basic_labels[0]["label"] if basic_labels else "General symptoms",
                "correlated_label": basic_labels[1]["label"] if len(basic_labels) > 1 else "Associated symptoms",
                "correlation_type": "commonly_associated",
                "clinical_significance": "Symptoms often present together in various conditions",
                "example": "Multiple symptoms may indicate systemic condition requiring evaluation"
            }
        ],
        "correlated_questions": questions,
        "medical_imaging_recommendations": [
            {
                "imaging_type": "Blood test",
                "reason": "Basic laboratory workup for symptom evaluation",
                "urgency": "routine",
                "uploadable": True,
                "target_labels": [label["label"] for label in basic_labels]
            },
            {
                "imaging_type": "X-ray",
                "reason": "Imaging if physical symptoms suggest structural issues",
                "urgency": "routine",
                "uploadable": True,
                "target_labels": [label["label"] for label in basic_labels if 'pain' in label["label"].lower()]
            }
        ]
    }

def generate_fallback_icd_diagnosis(patient_data):
    """Generate fallback ICD diagnosis when GPT-4 fails"""
    
    # Get basic patient info for diagnosis context
    registration = patient_data.get('registration', {})
    age = registration.get('calculated_age') or registration.get('age', 'Unknown')
    gender = registration.get('gender', 'Unknown')
    vitals = patient_data.get('vitals', {})
    complaints = patient_data.get('complaints', {})
    
    # Basic ICD codes based on common presentations
    fallback_diagnoses = [
        {
            "rank": 1,
            "icd_code": "Z00.00",
            "disease_name": "Encounter for general adult medical examination without abnormal findings",
            "common_name": "General health checkup",
            "confidence_percentage": 70,
            "evidence_score": "MEDIUM",
            "supporting_data": ["Patient presenting for medical assessment"],
            "icd_category": "General Medical",
            "clinical_reasoning": "Default diagnosis for general medical evaluation without specific abnormal findings"
        },
        {
            "rank": 2,
            "icd_code": "R50.9",
            "disease_name": "Fever, unspecified",
            "common_name": "Fever of unknown origin",
            "confidence_percentage": 50,
            "evidence_score": "LOW",
            "supporting_data": ["General symptom assessment"],
            "icd_category": "Symptoms and Signs",
            "clinical_reasoning": "Common presenting symptom requiring evaluation"
        },
        {
            "rank": 3,
            "icd_code": "R06.02",
            "disease_name": "Shortness of breath",
            "common_name": "Difficulty breathing",
            "confidence_percentage": 45,
            "evidence_score": "LOW",
            "supporting_data": ["Respiratory symptom evaluation"],
            "icd_category": "Respiratory",
            "clinical_reasoning": "Common respiratory complaint"
        }
    ]
    
    # Adjust based on actual patient data if available
    if complaints.get('raw_text'):
        complaint_text = complaints['raw_text'].lower()
        if 'pain' in complaint_text:
            fallback_diagnoses.insert(1, {
                "rank": 2,
                "icd_code": "R52",
                "disease_name": "Pain, unspecified",
                "common_name": "General pain",
                "confidence_percentage": 60,
                "evidence_score": "MEDIUM",
                "supporting_data": ["Patient reports pain symptoms"],
                "icd_category": "Symptoms and Signs",
                "clinical_reasoning": "Patient-reported pain requiring evaluation"
            })
    
    return {
        "icd_diagnoses": fallback_diagnoses[:10],  # Max 10 diagnoses
        "primary_icd": {
            "icd_code": fallback_diagnoses[0]["icd_code"],
            "disease_name": fallback_diagnoses[0]["disease_name"],
            "confidence": f"{fallback_diagnoses[0]['confidence_percentage']}%",
            "rationale": "Most appropriate diagnosis based on available information"
        },
        "system_analysis": {
            "total_data_points": "Limited data available for analysis",
            "key_indicators": ["Basic patient presentation", "General medical assessment"],
            "excluded_codes": ["Specific disease codes pending additional evaluation"],
            "diagnostic_certainty": "Low - requires additional clinical assessment"
        },
        "icd_coding_notes": {
            "coding_methodology": "Conservative approach using general diagnostic codes",
            "differential_approach": "Broad differential pending additional information",
            "limitations": "Limited patient data available for specific diagnosis"
        }
    }

def save_step_based_patient_data(step_number, form_data, ai_data=None, files_data=None):
    """
    Save all patient data in a highly organized step-based structure
    Each step has its own section with all values saved (user input, AI-generated, dynamic)
    One-to-one mapping between steps and data for easy reference
    
    OVERWRITE LOGIC:
    - If a field is provided in new data, it replaces the existing value
    - If a field is not provided (None, empty string, or missing), it's removed from storage
    - This ensures clean data without stale values
    """
    try:
        # Load existing data or create new with proper structure
        patient_data = load_patient_data() or {}
        
        # Initialize with metadata if new file
        if not patient_data:
            patient_data = {
                'session_info': {
                    'session_id': session.get('session_id', str(uuid.uuid4())),
                    'created_at': datetime.now().isoformat(),
                    'last_updated': datetime.now().isoformat()
                },
                'step1': {},
                'step2': {},
                'step3': {},
                'step4': {},
                'step5': {},
                'step6': {},
                'step7': {},
                'step_completion_status': {}
            }
        
        # Clean function to remove any existing suffixes before saving
        def clean_value(value):
            """Remove -A and -O suffixes if they exist"""
            if isinstance(value, str) and (value.endswith('-A') or value.endswith('-O')):
                return value[:-2]
            return value
        
        def is_valid_value(value, field_name=None):
            """Check if a value should be saved (not None, not empty string, not just whitespace, not 'none' values for certain fields)"""
            print(f"🔍 is_valid_value called: field='{field_name}', value='{value}'")
            
            if value is None:
                print(f"❌ REJECTED: {field_name} - value is None")
                return False
            if isinstance(value, str):
                # Convert to lowercase for comparison
                clean_value = value.strip().lower()
                print(f"🔤 Cleaned value: '{clean_value}'")
                
                # Don't save empty strings or whitespace
                if not clean_value:
                    print(f"❌ REJECTED: {field_name} - empty string")
                    return False
                
                # Field-specific filtering for medical conditions that use "none"/"no" to indicate absence
                # Note: For fields like lung_congestion, "none" is a valid selection meaning "no congestion"
                text_input_medical_fields = [
                    'infection_type', 'medical_condition', 'symptoms',
                    'complications', 'allergies', 'current_medications', 'ecg_findings'
                ]
                
                if field_name and field_name in text_input_medical_fields:
                    print(f"🏥 Text medical field detected: {field_name}")
                    # For text input medical condition fields, "none", "no", "normal" etc. mean "no condition present"
                    if clean_value in ['none', 'no', 'normal', 'n/a', 'na', 'not applicable', 'nil', 'nothing']:
                        print(f"❌ REJECTED: {field_name} - medical condition 'none' value: '{clean_value}'")
                        return False
                
                # Special handling for ECG availability
                if field_name == 'ecg_available' and clean_value == 'no':
                    print(f"✅ ACCEPTED: {field_name} - ECG 'no' is valid")
                    # For ECG availability, "no" is a valid response meaning "ECG not available"
                    return True
                    
            if isinstance(value, dict) and not value:
                print(f"❌ REJECTED: {field_name} - empty dict")
                return False
            if isinstance(value, list) and not value:
                print(f"❌ REJECTED: {field_name} - empty list")
                return False
            
            print(f"✅ ACCEPTED: {field_name} - value passed all checks")
            return True
        
        # Clean and filter form data - only save valid values
        cleaned_form_data = {}
        for key, value in form_data.items():
            print(f"🔍 FILTERING: {key} = '{value}'")
            if is_valid_value(value, key):
                cleaned_form_data[key] = clean_value(value)
                print(f"✅ KEPT: {key} = '{clean_value(value)}'")
            else:
                print(f"❌ REMOVED: {key} = '{value}' (filtered out by is_valid_value)")
        
        print(f"📝 FINAL CLEANED DATA: {cleaned_form_data}")
        
        # Clean and filter AI data - only save valid values
        cleaned_ai_data = {}
        if ai_data:
            for key, value in ai_data.items():
                if is_valid_value(value, key):
                    cleaned_ai_data[key] = clean_value(value)
        
        # Clean and filter files data - only save valid values
        cleaned_files_data = {}
        if files_data:
            for key, value in files_data.items():
                if is_valid_value(value, key):
                    cleaned_files_data[key] = value
        
        print(f"📝 OVERWRITE MODE - Step {step_number} data being completely replaced")
        print(f"   Form fields being saved: {list(cleaned_form_data.keys())}")
        print(f"   AI fields being saved: {list(cleaned_ai_data.keys())}")
        print(f"   File fields being saved: {list(cleaned_files_data.keys())}")
        
        # Update session metadata
        patient_data['session_info']['last_updated'] = datetime.now().isoformat()
        if f'step{step_number}' not in patient_data['session_info']:
            patient_data['session_info'][f'highest_step_completed'] = max(
                patient_data['session_info'].get('highest_step_completed', 0), 
                step_number
            )
        
        # STEP 1: Case Category and Basic Info
        if step_number == 1:
            # Completely replace step1 data with new data (overwrite mode)
            patient_data['step1'] = {
                'step_name': 'Case Category Selection',
                'form_data': cleaned_form_data,
                'ai_generated_data': cleaned_ai_data,
                'files_uploaded': cleaned_files_data,
                'timestamp': datetime.now().isoformat(),
                'data_source': 'user_input',
                'step_completed': True
            }
            print(f"✅ Step 1 data completely overwritten")
        
        # STEP 2: Patient Registration
        elif step_number == 2:
            # Completely replace step2 data with new data (overwrite mode)
            patient_data['step2'] = {
                'step_name': 'Patient Registration',
                'form_data': cleaned_form_data,
                'ai_generated_data': cleaned_ai_data,
                'files_uploaded': cleaned_files_data,
                'timestamp': datetime.now().isoformat(),
                'data_source': 'user_input_and_extraction',
                'step_completed': True
            }
            print(f"✅ Step 2 data completely overwritten")
        
        # STEP 3: Vital Signs and Medical Photos
        elif step_number == 3:
            # Completely replace step3 data with new data (overwrite mode)
            patient_data['step3'] = {
                'step_name': 'Vital Signs & Medical Photos',
                'form_data': cleaned_form_data,
                'ai_generated_data': cleaned_ai_data,
                'files_uploaded': cleaned_files_data,
                'timestamp': datetime.now().isoformat(),
                'data_source': 'user_input_and_analysis',
                'step_completed': True
            }
            print(f"✅ Step 3 data completely overwritten")
        
        # STEP 4: Medical Records, Contact & Medications
        elif step_number == 4:
            # Completely replace step4 data with new data (overwrite mode)
            patient_data['step4'] = {
                'step_name': 'Medical Records & Contact Information',
                'form_data': cleaned_form_data,
                'ai_generated_data': cleaned_ai_data,
                'files_uploaded': cleaned_files_data,
                'timestamp': datetime.now().isoformat(),
                'data_source': 'user_input_and_analysis',
                'step_completed': True
            }
            print(f"✅ Step 4 data completely overwritten")
        
        # STEP 5: Complaints and Symptoms
        elif step_number == 5:
            # Completely replace step5 data with new data (overwrite mode)
            patient_data['step5'] = {
                'step_name': 'Complaints & Symptoms',
                'form_data': cleaned_form_data,
                'ai_generated_data': cleaned_ai_data,
                'files_uploaded': cleaned_files_data,
                'timestamp': datetime.now().isoformat(),
                'data_source': 'user_input_and_ai_analysis',
                'step_completed': True
            }
            print(f"✅ Step 5 data completely overwritten")
        
        # STEP 6: Analysis and Diagnosis
        elif step_number == 6:
            # Completely replace step6 data with new data (overwrite mode)
            patient_data['step6'] = {
                'step_name': 'Analysis & Diagnosis',
                'form_data': cleaned_form_data,
                'ai_generated_data': cleaned_ai_data,
                'files_uploaded': cleaned_files_data,
                'timestamp': datetime.now().isoformat(),
                'data_source': 'ai_analysis',
                'step_completed': True
            }
            print(f"✅ Step 6 data completely overwritten")
        
        # STEP 7: ICD11 Code Generation and Analysis
        elif step_number == 7:
            # Completely replace step7 data with new data (overwrite mode)
            patient_data['step7'] = {
                'step_name': 'ICD11 Code Generation & Analysis',
                'form_data': cleaned_form_data,
                'ai_generated_data': cleaned_ai_data,
                'files_uploaded': cleaned_files_data,
                'timestamp': datetime.now().isoformat(),
                'data_source': 'icd_generation',
                'step_completed': True
            }
            print(f"✅ Step 7 data completely overwritten")
        
        # Update step completion status
        step_key = f'step{step_number}'
        patient_data['step_completion_status'][step_key] = {
            'completed': True,
            'timestamp': datetime.now().isoformat(),
            'form_fields_count': len(cleaned_form_data),
            'ai_fields_count': len(cleaned_ai_data),
            'files_count': len(cleaned_files_data)
        }
        
        # Update the step_completed field that validate_session_step checks
        current_step_completed = patient_data.get('step_completed', 0)
        patient_data['step_completed'] = max(current_step_completed, step_number)
        print(f"✅ Updated step_completed to {patient_data['step_completed']}")
        
        # Save to file with overwrite protection
        success = save_patient_data(patient_data)
        if success:
            print(f"✅ Step-based data saved successfully for step {step_number}")
            print(f"   📋 Form fields: {len(cleaned_form_data)}")
            print(f"   🤖 AI fields: {len(cleaned_ai_data)}")
            print(f"   📎 Files: {len(cleaned_files_data)}")
            return True
        else:
            print(f"❌ Failed to save step-based data for step {step_number}")
            return False
            
    except Exception as e:
        print(f"❌ Error in save_step_based_patient_data: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

def validate_overwrite_behavior():
    """
    Validation function to demonstrate proper overwrite behavior:
    - If a field is provided in new data, it replaces the existing value
    - If a field is not provided (None, empty string, or missing), it's removed from storage
    - This ensures clean data without stale values
    """
    print("🔍 OVERWRITE BEHAVIOR VALIDATION")
    print("="*50)
    print("✅ When saving step data:")
    print("   • Provided fields → Replace existing values")
    print("   • Empty/missing fields → Remove from storage") 
    print("   • No merge or append - complete replacement")
    print("   • Prevents stale data accumulation")
    print("   • Ensures data integrity and consistency")
    print("="*50)

def get_step_data(step_number):
    """
    Retrieve data for a specific step from the step-based structure
    """
    try:
        patient_data = load_patient_data()
        if not patient_data:
            return {}
        
        step_key = f'step{step_number}'
        if step_key in patient_data:
            return patient_data[step_key]
        
        return {}
    except Exception as e:
        print(f"Error retrieving step {step_number} data: {str(e)}")
        return {}

def get_all_patient_data():
    """
    Retrieve all patient data in organized step-based format
    """
    try:
        patient_data = load_patient_data()
        if not patient_data:
            return {}
        
        organized_data = {
            'session_info': patient_data.get('session_info', {}),
            'steps': {},
            'completion_status': patient_data.get('step_completion_status', {})
        }
        
        # Collect all step data (1-6 only, step 7 removed)
        for step_num in range(1, 7):
            step_key = f'step{step_num}'
            if step_key in patient_data:
                organized_data['steps'][step_key] = patient_data[step_key]
        
        return organized_data
    except Exception as e:
        print(f"Error retrieving all patient data: {str(e)}")
        return {}

def save_comprehensive_patient_data(step_number, form_data, ai_data=None, files_data=None):
    """
    Legacy function that now calls the new step-based save function
    """
    return save_step_based_patient_data(step_number, form_data, ai_data, files_data)

def migrate_legacy_data_to_step_based():
    """
    Migrate existing patient data to new step-based structure
    """
    try:
        patient_data = load_patient_data()
        if not patient_data:
            return False
        
        # Check if already in new format
        if 'step1' in patient_data or 'session_info' in patient_data:
            print("📊 Data already in new step-based format")
            return True
        
        print("🔄 Migrating legacy data to step-based structure...")
        
        # Create new structure
        new_data = {
            'session_info': {
                'session_id': patient_data.get('session_id', str(uuid.uuid4())),
                'created_at': patient_data.get('created_at', datetime.now().isoformat()),
                'last_updated': datetime.now().isoformat(),
                'highest_step_completed': patient_data.get('step_completed', 0)
            },
            'step1': {},
            'step2': {},
            'step3': {},
            'step4': {},
            'step5': {},
            'step6': {},
            'step_completion_status': {}
        }
        
        # Migrate step 1 data (case category)
        if 'case_category' in patient_data:
            new_data['step1'] = {
                'step_name': 'Case Category Selection',
                'form_data': patient_data['case_category'],
                'ai_generated_data': {},
                'files_uploaded': {},
                'timestamp': patient_data['case_category'].get('completed_at', datetime.now().isoformat()),
                'data_source': 'user_input',
                'step_completed': True
            }
            new_data['step_completion_status']['step_1'] = {
                'completed': True,
                'completed_at': patient_data['case_category'].get('completed_at', datetime.now().isoformat()),
                'data_saved': True
            }
        
        # Migrate step 2 data (registration)
        if 'registration' in patient_data:
            reg_data = patient_data['registration']
            
            # Clean suffixes from legacy data
            cleaned_reg_data = {}
            for key, value in reg_data.items():
                if isinstance(value, str) and (value.endswith('-A') or value.endswith('-O')):
                    cleaned_reg_data[key] = value[:-2]
                elif key not in ['action_data', 'outcome_data', 'completed_at', 'action_fields_processed', 'outcome_fields_processed']:
                    cleaned_reg_data[key] = value
            
            new_data['step2'] = {
                'step_name': 'Patient Registration',
                'form_data': cleaned_reg_data,
                'ai_generated_data': {
                    'aadhaar_extraction': reg_data.get('aadhaar_extraction', {}),
                    'emr_insights': reg_data.get('emr_insights', '')
                },
                'files_uploaded': {},
                'timestamp': reg_data.get('completed_at', datetime.now().isoformat()),
                'data_source': 'user_input_and_extraction',
                'step_completed': True
            }
            new_data['step_completion_status']['step_2'] = {
                'completed': True,
                'completed_at': reg_data.get('completed_at', datetime.now().isoformat()),
                'data_saved': True
            }
        
        # Migrate step 3 data (vitals)
        if 'vitals' in patient_data:
            vitals_data = patient_data['vitals']
            
            # Separate AI insights from form data
            form_data = {}
            ai_data = {}
            
            for key, value in vitals_data.items():
                if 'ai_insights' in key or 'photo_analysis' in key:
                    ai_data[key] = value
                elif key not in ['completed_at']:
                    form_data[key] = value
            
            new_data['step3'] = {
                'step_name': 'Vital Signs & Medical Photos',
                'form_data': form_data,
                'ai_generated_data': ai_data,
                'files_uploaded': {},
                'timestamp': vitals_data.get('completed_at', datetime.now().isoformat()),
                'data_source': 'user_input_and_analysis',
                'step_completed': True
            }
            new_data['step_completion_status']['step_3'] = {
                'completed': True,
                'completed_at': vitals_data.get('completed_at', datetime.now().isoformat()),
                'data_saved': True
            }
        
        # Migrate other steps if they exist
        step_map = {
            'step4_data': ('step4', 'Medical Records & Contact Information'),
            'complaints': ('step5', 'Complaints & Symptoms'),
            'complaint_analysis': ('step6', 'Complaint Analysis'),
            'diagnosis': ('step7', 'Final Diagnosis')
        }
        
        for legacy_key, (new_key, step_name) in step_map.items():
            if legacy_key in patient_data:
                new_data[new_key] = {
                    'step_name': step_name,
                    'form_data': patient_data[legacy_key],
                    'ai_generated_data': {},
                    'files_uploaded': {},
                    'timestamp': datetime.now().isoformat(),
                    'data_source': 'migrated_legacy',
                    'step_completed': True
                }
        
        # Preserve some legacy fields for compatibility
        new_data['step_completed'] = patient_data.get('step_completed', 0)
        new_data['last_updated'] = datetime.now().isoformat()
        new_data['data_timestamps'] = patient_data.get('data_timestamps', {})
        new_data['llm_timestamps'] = patient_data.get('llm_timestamps', {})
        
        # Save migrated data
        success = save_patient_data(new_data)
        if success:
            print("✅ Legacy data migrated successfully to step-based structure")
            return True
        else:
            print("❌ Failed to save migrated data")
            return False
        
    except Exception as e:
        print(f"❌ Error migrating legacy data: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

@app.route('/migrate_data', methods=['POST'])
def migrate_data():
    """Admin route to migrate legacy data to new structure"""
    try:
        success = migrate_legacy_data_to_step_based()
        return jsonify({
            'success': success,
            'message': 'Data migration completed successfully' if success else 'Data migration failed'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Migration error: {str(e)}'})

@app.route('/test_step_structure', methods=['GET'])
def test_step_structure():
    """Test route to verify the new step-based structure"""
    try:
        all_data = get_all_patient_data()
        
        # Analyze structure
        structure_info = {
            'has_session_info': 'session_info' in all_data,
            'has_steps': 'steps' in all_data,
            'available_steps': list(all_data.get('steps', {}).keys()),
            'completion_status': all_data.get('completion_status', {}),
            'total_data_size': len(str(all_data)),
        }
        
        # Test data retrieval for each step
        step_tests = {}
        for step_num in range(1, 8):
            step_data = get_step_data(step_num)
            step_tests[f'step{step_num}'] = {
                'has_data': bool(step_data),
                'form_fields': len(step_data.get('form_data', {})),
                'ai_fields': len(step_data.get('ai_generated_data', {})),
                'files': len(step_data.get('files_uploaded', {})),
                'completed': step_data.get('step_completed', False)
            }
        
        return jsonify({
            'success': True,
            'structure_info': structure_info,
            'step_tests': step_tests,
            'raw_data_sample': {k: str(v)[:100] + '...' if len(str(v)) > 100 else v 
                               for k, v in list(all_data.items())[:3]}
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': f'Test error: {str(e)}'})

# Routes
@app.route('/')
def home():
    initialize_session()
    return render_template('index.html')

# Session management routes
@app.route('/get_session_info')
def get_session_info():
    initialize_session()
    patient_data = session.get('patient_data', {})
    return jsonify({
        'success': True,
        'step_completed': patient_data.get('step_completed', 0),
        'session_id': patient_data.get('session_id', '')
    })

@app.route('/clear_session', methods=['POST'])
def clear_session():
    session.clear()
    return jsonify({'success': True, 'message': 'Session cleared successfully'})

# Step 1: Case Category Selection
@app.route('/step1')
def step1():
    # Clear all previous patient data when starting a new assessment
    clear_all_patient_data()
    initialize_session()
    return render_template('step1.html')

@app.route('/save_case_category', methods=['POST'])
def save_case_category():
    try:
        print("✅ Starting save_case_category")
        initialize_session()
        
        # Get request data
        data = request.get_json()
        case_category = data.get('case_category')
        case_description = data.get('case_description', '')
        
        if not case_category or case_category not in ['accident', 'illness']:
            return jsonify({'success': False, 'error': 'Invalid case category selected'})
        
        # Prepare form data for step-based saving
        form_data = {
            'case_category': case_category,
            'case_description': case_description if case_description else ''
        }
        
        # Use new step-based save function
        success = save_step_based_patient_data(
            step_number=1,
            form_data=form_data,
            ai_data={},
            files_data={}
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save case category data'})
        
        # Keep minimal data in session for navigation
        if 'patient_data' not in session:
            session['patient_data'] = {}
        session['patient_data']['step_completed'] = 1
        session.modified = True
        
        print(f"✅ Case category saved successfully: {case_category}")
        return jsonify({'success': True, 'message': 'Case category saved successfully'})
        
    except Exception as e:
        print(f"❌ Error in save_case_category: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to save case category: {str(e)}'})

def invalidate_downstream_steps(from_step):
    """Clear data from downstream steps when earlier step is modified"""
    try:
        patient_data = session.get('patient_data', {})
        
        if from_step <= 1:
            # Clear all downstream data from step 2 onwards
            patient_data['registration'] = {}
            patient_data['vitals'] = {}
            patient_data['follow_up_questions'] = {}
            patient_data['complaints'] = {}
            patient_data['complaint_analysis'] = {}
            patient_data['diagnosis'] = {}
        elif from_step <= 2:
            # Clear from step 3 onwards
            patient_data['vitals'] = {}
            patient_data['follow_up_questions'] = {}
            patient_data['complaints'] = {}
            patient_data['complaint_analysis'] = {}
            patient_data['diagnosis'] = {}
        elif from_step <= 3:
            # Clear from step 5 onwards (step 4 removed)
            patient_data['follow_up_questions'] = {}
            patient_data['complaints'] = {}
            patient_data['complaint_analysis'] = {}
            patient_data['diagnosis'] = {}
        elif from_step <= 4:
            # Clear from step 5 onwards
            patient_data['complaints'] = {}
            patient_data['complaint_analysis'] = {}
            patient_data['diagnosis'] = {}
        elif from_step <= 5:
            # Clear from step 6 onwards
            patient_data['complaint_analysis'] = {}
            patient_data['diagnosis'] = {}
        elif from_step <= 6:
            # Clear diagnosis only
            patient_data['diagnosis'] = {}
        
        # Reset step completed to current step
        patient_data['step_completed'] = from_step
        session.modified = True
        print(f"Invalidated downstream steps from step {from_step}")
    except Exception as e:
        print(f"Error invalidating downstream steps from step {from_step}: {str(e)}")

# Step 2: Patient Registration
@app.route('/step2')
def step2():
    if not validate_session_step(1):
        return redirect('/')
    return render_template('step2.html')

# Global mapping for Action (A) and Outcome (O) categories for Step 2
STEP2_FIELD_CATEGORIES = {
    # Action fields (for documentation and doctor identification)
    'full_name': 'A',
    'address': 'A',
    'phone': 'A',
    'email': 'A',
    'language': 'A',
    'emergency_name': 'A',
    'emergency_relation': 'A',
    'emergency_phone': 'A',
    'marital_status': 'A',
    'education_level': 'A',
    'employment_status': 'A',
    'economic_status': 'A',
    'income_source': 'A',
    'family_history': 'A',
    'emr_existing': 'A',
    'emr_register': 'A',
    'insurance_doc': 'A',
    'vaccine_doc': 'A',
    'health_card': 'A',
    'aadhar_front': 'A',
    'aadhar_back': 'A',
    'aadhar_combined': 'A',
    
    # Outcome fields (required for diagnosis)
    'date_of_birth': 'O',  # For age calculation
    'calculated_age': 'O',
    'gender': 'O',
    'occupation': 'O',
    'occupation_detail': 'O',
    'diabetes': 'O',
    'hypertension': 'O',
    'asthma': 'O',
    'heart_disease': 'O'
}

def categorize_step2_data(form_data):
    """Categorize Step 2 data into Action and Outcome categories"""
    action_data = {}
    outcome_data = {}
    
    for field_name, value in form_data.items():
        category = STEP2_FIELD_CATEGORIES.get(field_name, 'A')  # Default to Action
        
        if category == 'A':
            action_data[field_name] = value
        else:
            outcome_data[field_name] = value
    
    return action_data, outcome_data

@app.route('/save_registration', methods=['POST'])
def save_registration():
    try:
        print("✅ Starting save_registration")
        initialize_session()
        
        # Validate that Step 1 (case category) is completed
        if not validate_session_step(1):
            return jsonify({'success': False, 'error': 'Please complete case category selection first'})
        
        # Check if this is a modification of existing data
        patient_data = load_patient_data()
        existing_step2 = get_step_data(2)
        is_modification = bool(existing_step2)
        
        # Collect all form data
        form_data = {}
        form_fields = [
            'full_name', 'date_of_birth', 'gender', 'address', 'phone', 'email',
            'language', 'emergency_name', 'emergency_relation', 'emergency_phone',
            'occupation', 'occupation_detail', 'marital_status', 'education_level',
            'employment_status', 'economic_status', 'income_source',
            'diabetes', 'hypertension', 'asthma', 'heart_disease', 'family_history',
            'calculated_age', 'lab_reports', 'medical_images', 'signaling_reports',
            'emr_existing', 'emr_register', 'currently_pregnant', 'pregnancy_month', 
            'recent_childbirth'
        ]
        
        for field in form_fields:
            value = request.form.get(field, '')
            if value:  # Only store non-empty values
                form_data[field] = value.strip()
        
        # Handle file uploads
        files_data = {}
        file_fields = ['aadhar_front', 'aadhar_back', 'aadhar_combined', 'insurance_doc', 'vaccine_doc', 'health_card']
        for field in file_fields:
            if field in request.files:
                file = request.files[field]
                if file and file.filename:
                    files_data[field] = {
                        'filename': file.filename,
                        'upload_timestamp': datetime.now().isoformat(),
                        'field_name': field,
                        'content_type': getattr(file, 'content_type', 'unknown')
                    }
                    print(f"📎 File uploaded for {field}: {file.filename}")
        
        # Collect AI data (like Aadhaar extraction, EMR analysis)
        ai_data = {}
        if 'aadhaar_extraction' in session.get('patient_data', {}).get('registration', {}):
            ai_data['aadhaar_extraction'] = session['patient_data']['registration']['aadhaar_extraction']
        if 'emr_insights' in session.get('patient_data', {}).get('registration', {}):
            ai_data['emr_insights'] = session['patient_data']['registration']['emr_insights']
        
        print(f"📋 Registration data collected: {len(form_data)} form fields")
        print(f"📎 Files uploaded: {len(files_data)}")
        print(f"🤖 AI data collected: {len(ai_data)}")
        
        # Use new step-based save function
        success = save_step_based_patient_data(
            step_number=2,
            form_data=form_data,
            ai_data=ai_data,
            files_data=files_data
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save registration data'})
        
        # If this is a modification, invalidate downstream steps
        if is_modification:
            invalidate_downstream_steps(2)
        
        # Keep minimal data in session for navigation
        if 'patient_data' not in session:
            session['patient_data'] = {}
        session['patient_data']['step_completed'] = 2
        session.modified = True
        
        print("✅ Registration saved successfully")
        return jsonify({
            'success': True, 
            'message': 'Registration completed successfully',
            'form_fields': len(form_data),
            'files_uploaded': len(files_data),
            'ai_data_fields': len(ai_data)
        })
        
    except Exception as e:
        print(f"❌ Error in save_registration: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to save registration: {str(e)}'})

# Helper function to get diagnosis-relevant data from Step 1
def get_step1_diagnosis_data():
    """Extract only diagnosis-relevant (Outcome) data from Step 1"""
    if 'patient_data' not in session or 'registration' not in session['patient_data']:
        return {}
    
    registration = session['patient_data']['registration']
    return registration.get('outcome_data', {})

@app.route('/analyze_emr', methods=['POST'])
def analyze_emr():
    """Analyze uploaded EMR document using LLM"""
    try:
        if 'emr_file' not in request.files:
            return jsonify({'success': False, 'error': 'No EMR file uploaded'})
        
        file = request.files['emr_file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        # Read file content
        file_content = file.read()
        file_type = file.content_type
        
        # Encode file content for API
        if file_type.startswith('image/'):
            # For images, use base64 encoding
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            content_type = "image"
        elif file_type == 'application/pdf':
            # For PDFs, use base64 encoding (OpenAI can handle PDF analysis)
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            content_type = "pdf"
        else:
            return jsonify({'success': False, 'error': 'Unsupported file type'})
        
        # Prepare LLM prompt for EMR analysis
        prompt = load_prompt("emr_analysis")

        # Make API call to OpenAI
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system", 
                    "content": load_prompt("emr_system")
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url" if content_type == "image" else "text",
                            "image_url": {
                                "url": f"data:{file_type};base64,{encoded_content}"
                            } if content_type == "image" else {"text": f"PDF Content (Base64): {encoded_content[:1000]}..."}
                        }
                    ]
                }
            ],
            max_tokens=500,
            temperature=0.3
        )
        
        insights = response.choices[0].message.content.strip()
        
        # Store abbreviated EMR insights to reduce session size
        if 'patient_data' not in session:
            session['patient_data'] = {}
        if 'registration' not in session['patient_data']:
            session['patient_data']['registration'] = {}
        
        # Store only abbreviated insights to avoid session size issues
        abbreviated_insights = insights[:300] + "..." if len(insights) > 300 else insights
        session['patient_data']['registration']['emr_insights'] = abbreviated_insights
        
        return jsonify({
            'success': True,
            'insights': insights
        })
        
    except Exception as e:
        print(f"EMR analysis error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error analyzing EMR: {str(e)}'
        })

@app.route('/process_aadhaar', methods=['POST'])
def process_aadhaar():
    """Process uploaded Aadhaar card image and extract data using LLM"""
    try:
        if 'aadhaar_image' not in request.files:
            return jsonify({'success': False, 'error': 'No Aadhaar image uploaded'})
        
        file = request.files['aadhaar_image']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        # Read file content
        file_content = file.read()
        file_type = file.content_type
        
        # Validate file type (only images)
        if not file_type.startswith('image/'):
            return jsonify({'success': False, 'error': 'Please upload a valid image file (JPG, PNG, etc.)'})
        
        # Encode image content for API
        encoded_content = base64.b64encode(file_content).decode('utf-8')
        
        # Prepare LLM prompt for Aadhaar analysis
        prompt = load_prompt("aadhaar_analysis")

        # Make API call to OpenAI for Aadhaar analysis
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system", 
                    "content": load_prompt("aadhaar_system")
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{file_type};base64,{encoded_content}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=800,
            temperature=0.1  # Low temperature for more accurate extraction
        )
        
        result = response.choices[0].message.content.strip()
        
        # Parse the JSON response
        if result.startswith('```json'):
            result = result[7:-3]
        elif result.startswith('```'):
            result = result[3:-3]
        
        result = result.strip()
        
        try:
            # Extract JSON from response
            json_start = result.find('{')
            json_end = result.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                raise Exception("No valid JSON found in response")
            
            json_content = result[json_start:json_end]
            extraction_result = json.loads(json_content)
            
            if extraction_result.get('success'):
                # Store Aadhaar data in session
                if 'patient_data' not in session:
                    session['patient_data'] = {}
                if 'registration' not in session['patient_data']:
                    session['patient_data']['registration'] = {}
                
                session['patient_data']['registration']['aadhaar_extraction'] = extraction_result['extracted_data']
                session.modified = True
                
                return jsonify(extraction_result)
            else:
                return jsonify({
                    'success': False,
                    'error': extraction_result.get('error', 'Failed to extract data from Aadhaar card')
                })
                
        except json.JSONDecodeError as e:
            print(f"JSON parsing error in Aadhaar extraction: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Failed to parse extraction results. Please try with a clearer image.'
            })
        
    except Exception as e:
        print(f"Aadhaar processing error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error processing Aadhaar card: {str(e)}'
        })

@app.route('/process_insurance_pdf', methods=['POST'])
def process_insurance_pdf():
    """Process uploaded insurance PDF document and extract ALL text using best model"""
    try:
        if 'insurance_document' not in request.files:
            return jsonify({'success': False, 'error': 'No insurance document uploaded'})
        
        file = request.files['insurance_document']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        # Read file content
        file_content = file.read()
        file_type = file.content_type
        
        # Validate file type (PDF or images)
        if not (file_type == 'application/pdf' or file_type.startswith('image/')):
            return jsonify({'success': False, 'error': 'Please upload a valid PDF file or image'})
        
        # Handle PDF files with comprehensive text extraction
        if file_type == 'application/pdf':
            try:
                import PyPDF2
                import io
                
                # Extract text from PDF using PyPDF2
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(file_content))
                extracted_text = ""
                
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    page_text = page.extract_text()
                    if page_text.strip():
                        extracted_text += f"=== PAGE {page_num} ===\n{page_text}\n\n"
                
                # Also try to extract images from PDF and analyze them with GPT-4o
                embedded_image_text = ""
                try:
                    # Convert PDF pages to images for comprehensive OCR using GPT-4o
                    # This ensures we get text from embedded images too
                    import fitz  # PyMuPDF for better PDF handling
                    
                    pdf_document = fitz.open(stream=file_content, filetype="pdf")
                    
                    for page_num in range(len(pdf_document)):
                        page = pdf_document.load_page(page_num)
                        # Convert page to image
                        mat = fitz.Matrix(2.0, 2.0)  # High resolution
                        pix = page.get_pixmap(matrix=mat)
                        img_data = pix.tobytes("png")
                        
                        # Encode image for GPT-4o
                        encoded_image = base64.b64encode(img_data).decode('utf-8')
                        
                        # Use GPT-4o for comprehensive OCR
                        ocr_prompt = load_prompt("pdf_ocr_analysis")
                        
                        ocr_response = openai_client.chat.completions.create(
                            model="gpt-4o",  # Best model for comprehensive OCR
                            messages=[
                                {
                                    "role": "system",
                                    "content": load_prompt("pdf_ocr_system")
                                },
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": ocr_prompt},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/png;base64,{encoded_image}"
                                            }
                                        }
                                    ]
                                }
                            ],
                            max_tokens=2000,
                            temperature=0.0  # Minimum temperature for maximum accuracy
                        )
                        
                        page_ocr_text = ocr_response.choices[0].message.content.strip()
                        if page_ocr_text:
                            embedded_image_text += f"=== PAGE {page_num + 1} (COMPREHENSIVE OCR) ===\n{page_ocr_text}\n\n"
                    
                    pdf_document.close()
                    
                except ImportError:
                    # Fallback if PyMuPDF not available
                    print("PyMuPDF not available, using basic PyPDF2 extraction only")
                except Exception as e:
                    print(f"Error in comprehensive PDF OCR: {str(e)}")
                
                # Combine extracted text
                final_text = ""
                if extracted_text.strip():
                    final_text += "=== BASIC TEXT EXTRACTION ===\n" + extracted_text
                if embedded_image_text.strip():
                    final_text += "=== COMPREHENSIVE OCR EXTRACTION ===\n" + embedded_image_text
                
                if not final_text.strip():
                    return jsonify({'success': False, 'error': 'Could not extract any text from PDF. Please try with an image version.'})
                
                # Store extracted text in patient data
                patient_data = load_patient_data()
                if 'registration' not in patient_data:
                    patient_data['registration'] = {}
                
                patient_data['registration']['insurance_extracted_text'] = {
                    'text': final_text,
                    'extraction_method': 'comprehensive_pdf_ocr',
                    'file_type': 'PDF',
                    'extracted_at': datetime.now().isoformat(),
                    'file_name': file.filename
                }
                
                save_patient_data(patient_data)
                
                return jsonify({
                    'success': True,
                    'extracted_text': final_text,
                    'extraction_method': 'comprehensive_pdf_ocr',
                    'file_type': 'PDF'
                })

            except ImportError:
                return jsonify({'success': False, 'error': 'PDF processing not available. Please upload an image version of your insurance document.'})
            except Exception as e:
                return jsonify({'success': False, 'error': f'Error reading PDF: {str(e)}'})
                
        else:
            # Handle image files with comprehensive OCR
            encoded_content = base64.b64encode(file_content).decode('utf-8')
            
            prompt = load_prompt("insurance_ocr_analysis")

            response = openai_client.chat.completions.create(
                model="gpt-4o",  # Best model for comprehensive OCR
                messages=[
                    {
                        "role": "system", 
                        "content": load_prompt("insurance_ocr_system")
                    },
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{file_type};base64,{encoded_content}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.0  # Minimum temperature for maximum accuracy
            )
        
            result = response.choices[0].message.content.strip()
            
            # Store extracted text in patient data
            patient_data = load_patient_data()
            if 'registration' not in patient_data:
                patient_data['registration'] = {}
            
            patient_data['registration']['insurance_extracted_text'] = {
                'text': result,
                'extraction_method': 'comprehensive_image_ocr',
                'file_type': 'Image',
                'extracted_at': datetime.now().isoformat(),
                'file_name': file.filename
            }
            
            save_patient_data(patient_data)
            
            return jsonify({
                'success': True,
                'extracted_text': result,
                'extraction_method': 'comprehensive_image_ocr',
                'file_type': 'Image'
            })
        
    except Exception as e:
        print(f"Insurance processing error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error processing insurance document: {str(e)}'
        })

@app.route('/get_insurance_text', methods=['GET'])
def get_insurance_text():
    """Retrieve saved insurance extracted text"""
    try:
        patient_data = load_patient_data()
        
        if 'registration' in patient_data and 'insurance_extracted_text' in patient_data['registration']:
            return jsonify({
                'success': True,
                'data': patient_data['registration']['insurance_extracted_text']
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No insurance text data found'
            })
            
    except Exception as e:
        print(f"Error retrieving insurance text: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error retrieving insurance text: {str(e)}'
        })

@app.route('/analyze_medical_photo', methods=['POST'])
def analyze_medical_photo():
    """Analyze uploaded medical photos (tongue, throat, skin/infection) using LLM"""
    try:
        if 'image' not in request.files:
            return jsonify({'success': False, 'error': 'No image uploaded'})
        
        file = request.files['image']
        photo_type = request.form.get('photo_type', 'unknown')
        category = request.form.get('category', photo_type)  # Support Step 3 categories
        report_type = request.form.get('report_type', '')   # Support Step 3 report types
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        # Read and encode file content
        file_content = file.read()
        file_type = file.content_type
        
        # Validate file type (only images)
        if not file_type.startswith('image/'):
            return jsonify({'success': False, 'error': 'Please upload a valid image file'})
        
        # Encode image content for API
        encoded_content = base64.b64encode(file_content).decode('utf-8')
        
        # Get the appropriate photo analysis prompt from external files
        if category in ['laboratory', 'medical_image', 'signal']:
            base_prompt = get_photo_analysis_prompt(category, None, report_type)
        else:
            base_prompt = get_photo_analysis_prompt(photo_type, None, report_type)
        
        full_prompt = f"""
        {base_prompt}
        
        RESPONSE FORMAT (JSON):
        {{
            "success": true,
            "insights": {{
                "general_findings": "Overall description of what is observed",
                "specific_observations": ["List of specific medical observations"],
                "confidence_level": "High/Medium/Low",
                "recommendations": "Medical recommendations and next steps",
                "concerns": ["List any concerning findings requiring attention"],
                "normal_features": ["List normal/healthy features observed"],
                "follow_up_needed": "Yes/No with explanation"
            }}
        }}
        
        IMPORTANT:
        - Provide medical observations only, not definitive diagnoses
        - Use professional medical terminology
        - Be specific about visual characteristics
        - Indicate confidence level in observations
        - Highlight any concerning features
        - Suggest appropriate medical follow-up when needed
        """

        # Make API call to OpenAI for medical photo analysis
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system", 
                    "content": load_prompt("photo_analysis_system")
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": full_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{file_type};base64,{encoded_content}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000,
            temperature=0.3  # Lower temperature for more consistent medical analysis
        )
        
        result = response.choices[0].message.content.strip()
        
        # Parse the JSON response
        if result.startswith('```json'):
            result = result[7:-3]
        elif result.startswith('```'):
            result = result[3:-3]
        
        result = result.strip()
        
        try:
            # Extract JSON from response
            json_start = result.find('{')
            json_end = result.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                raise Exception("No valid JSON found in response")
            
            json_content = result[json_start:json_end]
            analysis_result = json.loads(json_content)
            
            if analysis_result.get('success'):
                # Store medical photo analysis in session
                if 'patient_data' not in session:
                    session['patient_data'] = {}
                
                # Handle Step 3 categories differently from Step 2
                if category in ['laboratory', 'medical_image', 'signal']:
                    # Step 3: Store minimal data to avoid session size issues
                    if 'medical_reports_analysis' not in session['patient_data']:
                        session['patient_data']['medical_reports_analysis'] = []
                    
                    # Store only essential metadata, not full analysis to reduce session size
                    session['patient_data']['medical_reports_analysis'].append({
                        'file_name': file.filename,
                        'category': category,
                        'report_type': report_type,
                        'analyzed': True,  # Just track that it was analyzed
                        'analyzed_at': datetime.now().isoformat()
                    })
                else:
                    # Step 2: Store abbreviated vitals analysis
                    if 'vitals' not in session['patient_data']:
                        session['patient_data']['vitals'] = {}
                    # Store only key points, not full analysis
                    insights = analysis_result['insights']
                    abbreviated_insights = insights[:200] + "..." if len(insights) > 200 else insights
                    session['patient_data']['vitals'][f'{photo_type}_photo_analysis'] = abbreviated_insights
                
                session.modified = True
                
                return jsonify(analysis_result)
            else:
                return jsonify({
                    'success': False,
                    'error': analysis_result.get('error', 'Failed to analyze medical photo')
                })
                
        except json.JSONDecodeError as e:
            print(f"JSON parsing error in medical photo analysis: {str(e)}")
            return jsonify({
                'success': False,
                'error': 'Failed to parse analysis results. Please try with a clearer image.'
            })
        
    except Exception as e:
        print(f"Medical photo analysis error: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error analyzing medical photo: {str(e)}'
        })

# Step 3: Vital Signs
@app.route('/step3')
def step3():
    if not validate_session_step(2):
        return redirect('/')
    
    # Load existing step3 data if available for editing
    all_data = get_all_patient_data()
    step3_data = {}
    if 'steps' in all_data and 'step3' in all_data['steps']:
        step3_data = all_data['steps']['step3'].get('form_data', {})
        print(f"✅ Loading existing step3 data for editing: {len(step3_data)} fields")
    
    return render_template('step3.html', step3_data=step3_data)

# Step 4: Medical Records & Contact
@app.route('/step4')
def step4():
    if not validate_session_step(3):
        return redirect('/')
    
    # Get patient data for display using new structure
    all_data = get_all_patient_data()
    patient_name = "Patient"
    patient_age = "Unknown"
    patient_gender = "Unknown"
    
    # Try to get patient info from step2
    if 'steps' in all_data and 'step2' in all_data['steps']:
        step2_data = all_data['steps']['step2'].get('form_data', {})
        patient_name = step2_data.get('full_name', 'Patient')
        patient_age = step2_data.get('calculated_age', 'Unknown')
        patient_gender = step2_data.get('gender', 'Unknown')
    
    # Load existing step4 data if available for editing
    step4_data = {}
    if 'steps' in all_data and 'step4' in all_data['steps']:
        step4_data = all_data['steps']['step4'].get('form_data', {})
    
    return render_template('step4.html', 
                         patient_name=patient_name,
                         patient_age=patient_age,
                         patient_gender=patient_gender,
                         step4_data=step4_data)

@app.route('/save_vitals', methods=['POST'])
def save_vitals():
    try:
        print("✅ Starting save_vitals function")
        print(f"📋 Form data keys: {list(request.form.keys())}")
        
        if not validate_session_step(2):
            print("❌ Validation failed for step 2")
            return jsonify({'success': False, 'error': 'Please complete registration first'})
        
        print("✅ Validation passed for step 2")
        
        # Check if this is a modification of existing data
        existing_step3 = get_step_data(3)
        is_modification = bool(existing_step3)
        print(f"🔄 Is modification: {is_modification}")
        
        # Collect all form data
        form_data = {}
        for key, value in request.form.items():
            print(f"🔍 RAW FORM DATA: {key} = '{value}' (type: {type(value)})")
            if value and str(value).strip():  # Only include non-empty values
                form_data[key] = value.strip()
                print(f"📝 INCLUDED: {key} = '{value.strip()}'")
            else:
                print(f"🚫 EXCLUDED: {key} = '{value}' (empty or None)")
        
        print(f"📋 Collected form data with {len(form_data)} fields")
        print(f"📋 Form data contents: {form_data}")
        
        # Handle file uploads for vitals (medical photos)
        files_data = {}
        photo_fields = ['tongue_photo', 'throat_photo', 'infection_photo']
        for field in photo_fields:
            if field in request.files:
                file = request.files[field]
                if file and file.filename:
                    files_data[field] = {
                        'filename': file.filename,
                        'upload_timestamp': datetime.now().isoformat(),
                        'file_size': len(file.read()),
                        'content_type': file.content_type,
                        'photo_type': field.replace('_photo', '')
                    }
                    file.seek(0)  # Reset file pointer
                    print(f"📸 Medical photo uploaded: {file.filename} ({field})")
        
        # Collect AI-generated insights from photo analysis
        ai_data = {}
        ai_fields = ['tongue_ai_insights', 'throat_ai_insights', 'infection_ai_insights']
        for field in ai_fields:
            if field in form_data:
                ai_data[field] = form_data[field]
                # Remove from form_data to avoid duplication
                del form_data[field]
        
        print(f"🤖 AI insights collected: {len(ai_data)} fields")
        print(f"📎 Files uploaded: {len(files_data)}")
        
        # Use new step-based save function
        print("🔄 About to call save_step_based_patient_data...")
        try:
            success = save_step_based_patient_data(
                step_number=3,
                form_data=form_data,
                ai_data=ai_data,
                files_data=files_data
            )
            print(f"💾 save_step_based_patient_data returned: {success}")
        except Exception as save_error:
            print(f"💥 Exception in save_step_based_patient_data: {str(save_error)}")
            import traceback
            traceback.print_exc()
            return jsonify({'success': False, 'error': f'Save error: {str(save_error)}'})

        if not success:
            print("❌ Step-based save failed")
            return jsonify({'success': False, 'error': 'Failed to save vitals data'})
        
        print("✅ Step-based save succeeded")
        
        # If this is a modification, invalidate downstream steps
        if is_modification:
            invalidate_downstream_steps(3)
        
        # Keep minimal data in session for navigation
        if 'patient_data' not in session:
            session['patient_data'] = {}
        session['patient_data']['step_completed'] = 3
        session.modified = True
        
        print("✅ Returning success response with redirect to step4")
        
        return jsonify({
            'success': True, 
            'message': 'Vitals saved successfully',
            'redirect_url': '/step4',
            'form_fields': len(form_data),
            'ai_insights': len(ai_data),
            'photos_uploaded': len(files_data)
        })
        
    except Exception as e:
        print(f"❌ ERROR in save_vitals: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to save vitals: {str(e)}'})

@app.route('/save_step4', methods=['POST'])
def save_step4():
    try:
        print("✅ Starting save_step4")
        
        if not validate_session_step(3):
            return jsonify({'success': False, 'error': 'Please complete vitals first'})
        
        # Check if this is a modification of existing data
        existing_step4 = get_step_data(4)
        is_modification = bool(existing_step4)
        print(f"🔄 Is modification: {is_modification}")
        
        # Collect all form data
        form_data = {}
        for key, value in request.form.items():
            if value and str(value).strip():  # Only include non-empty values
                form_data[key] = value.strip()
        
        print(f"📋 Form data collected: {len(form_data)} fields")
        
        # Handle file uploads for medical documents
        files_data = {}
        file_mappings = {
            'lab_report_file': 'lab_report',
            'medical_image_file': 'medical_imaging',
            'pathology_report_file': 'pathology_report',
            'signaling_report_file': 'signaling_report'
        }
        
        for form_field, report_type in file_mappings.items():
            if form_field in request.files:
                file = request.files[form_field]
                if file and file.filename:
                    files_data[report_type] = {
                        'filename': file.filename,
                        'upload_timestamp': datetime.now().isoformat(),
                        'file_size': len(file.read()),
                        'content_type': file.content_type,
                        'report_type': form_data.get(f'{report_type}_type', ''),
                        'category': report_type
                    }
                    file.seek(0)  # Reset file pointer
                    print(f"📄 Medical document uploaded: {file.filename} ({report_type})")
        
        # Collect AI-generated insights
        ai_data = {}
        ai_fields = [
            'lab_ai_insights', 'image_ai_insights', 'pathology_ai_insights', 
            'signaling_ai_insights', 'generated_questions'
        ]
        
        for field in ai_fields:
            if field in form_data:
                ai_data[field] = form_data[field]
                # Remove from form_data to avoid duplication
                del form_data[field]
        
        # Collect follow-up question answers
        followup_answers = {}
        for key in list(form_data.keys()):
            if key.startswith('followup_answer_'):
                question_id = key.replace('followup_answer_', '')
                followup_answers[question_id] = {
                    'answer': form_data[key],
                    'answered_at': datetime.now().isoformat()
                }
                del form_data[key]  # Remove from form_data
        
        if followup_answers:
            ai_data['followup_answers'] = followup_answers
            print(f"📝 Follow-up answers collected: {len(followup_answers)}")
        
        print(f"🤖 AI insights collected: {len(ai_data)} fields")
        print(f"📎 Files uploaded: {len(files_data)}")
        
        # Use new step-based save function
        success = save_step_based_patient_data(
            step_number=4,
            form_data=form_data,
            ai_data=ai_data,
            files_data=files_data
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save step 4 data'})
        
        # If modification, invalidate downstream steps
        if is_modification:
            invalidate_downstream_steps(4)
        
        # Get patient summary for response
        all_data = get_all_patient_data()
        patient_name = 'Patient'
        
        # Try to get patient name from any step
        for step_key in ['step1', 'step2']:
            if step_key in all_data.get('steps', {}):
                step_data = all_data['steps'][step_key]
                name = step_data.get('form_data', {}).get('full_name')
                if name:
                    patient_name = name
                    break
        
        # Count active medications
        active_medications = []
        step4_form_data = form_data
        for key in step4_form_data:
            if key.endswith('_medication') and step4_form_data[key]:
                med_type = key.replace('_medication', '').replace('_', ' ').title()
                active_medications.append(f"{med_type}: {step4_form_data[key]}")
        
        # Emergency contact info
        emergency_name = step4_form_data.get('emergency_name', 'Not provided')
        emergency_relation = step4_form_data.get('emergency_relation', '')
        emergency_contact_display = f"{emergency_name} ({emergency_relation})" if emergency_relation else emergency_name
        
        # Keep minimal data in session for navigation
        if 'patient_data' not in session:
            session['patient_data'] = {}
        
        session['patient_data']['step_completed'] = 4
        session['patient_data']['step4_completed'] = True
        session.modified = True
        
        print("✅ Step 4 data saved successfully")
        
        return jsonify({
            'success': True, 
            'message': 'Medical records and contact information saved successfully',
            'redirect_url': '/step5',
            'patient_name': patient_name,
            'summary': {
                'form_fields': len(form_data),
                'ai_insights': len(ai_data),
                'files_uploaded': len(files_data),
                'medications_count': len(active_medications),
                'emergency_contact': emergency_contact_display,
                'followup_answers': len(followup_answers) if followup_answers else 0
            }
        })
        
    except Exception as e:
        print(f"❌ ERROR in save_step4: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to save step 4: {str(e)}'})

# Step 5: Complaints and Symptoms
@app.route('/step5')
def step5():
    if not validate_session_step(4):
        return redirect('/')
    
    # Get patient data for display
    all_data = get_all_patient_data()
    patient_name = "Patient"
    patient_age = "Unknown"
    patient_gender = "Unknown"
    
    # Try to get patient info from step2
    if 'steps' in all_data and 'step2' in all_data['steps']:
        step2_data = all_data['steps']['step2'].get('form_data', {})
        patient_name = step2_data.get('full_name', 'Patient')
        patient_age = step2_data.get('calculated_age', 'Unknown')
        patient_gender = step2_data.get('gender', 'Unknown')
    
    # Load existing step5 data if available for editing
    step5_data = {}
    if 'steps' in all_data and 'step5' in all_data['steps']:
        step5_data = all_data['steps']['step5'].get('form_data', {})
        print(f"✅ Loading existing step5 data for editing: {len(step5_data)} fields")
    
    # Extract abnormal findings from step4 data
    abnormal_findings = []
    if 'steps' in all_data and 'step4' in all_data['steps']:
        step4_ai_data = all_data['steps']['step4'].get('ai_generated_data', {})
        generated_questions_str = step4_ai_data.get('generated_questions', '[]')
        
        try:
            import json
            if isinstance(generated_questions_str, str):
                generated_questions = json.loads(generated_questions_str)
            else:
                generated_questions = generated_questions_str
            
            # Use a set to track unique findings and avoid duplicates
            unique_findings = {}
            
            # Extract unique abnormal findings from the questions
            for question_data in generated_questions:
                if isinstance(question_data, dict) and 'abnormal_finding' in question_data:
                    finding_key = question_data.get('abnormal_finding', '').lower().strip()
                    if finding_key and finding_key not in unique_findings:
                        unique_findings[finding_key] = {
                            'finding': question_data.get('abnormal_finding', ''),
                            'concern': question_data.get('medical_concern', ''),
                            'priority': question_data.get('priority', 'normal'),
                            'question': question_data.get('question', '')
                        }
            
            # Convert unique findings to list
            abnormal_findings = list(unique_findings.values())
            
            print(f"✅ Extracted {len(abnormal_findings)} unique abnormal findings from step4 (filtered from {len(generated_questions)} questions)")
        except Exception as e:
            print(f"⚠️ Error parsing step4 generated_questions: {e}")
            abnormal_findings = []
    
    return render_template('step5.html', 
                         patient_name=patient_name,
                         patient_age=patient_age,
                         patient_gender=patient_gender,
                         step5_data=step5_data,
                         abnormal_findings=abnormal_findings)

@app.route('/analyze_symptoms_quick', methods=['POST'])
def analyze_symptoms_quick():
    """Quick insights on symptoms - extract medical labels"""
    try:
        print("🔍 Starting quick symptom analysis...")
        
        if not validate_session_step(4):
            return jsonify({'success': False, 'error': 'Please complete step 4 first'})
        
        # Get symptom text from request
        complaint_text = request.json.get('symptoms', '').strip()
        if not complaint_text:
            return jsonify({'success': False, 'error': 'Please enter symptom description first'})
        
        print(f"📝 Analyzing complaint: {complaint_text[:100]}...")
        
        # Get patient context for better analysis
        all_data = get_all_patient_data()
        patient_context = {
            'age': 'Unknown',
            'gender': 'Unknown',
            'vitals': {}
        }
        
        # Extract context from previous steps
        if 'steps' in all_data:
            if 'step2' in all_data['steps']:
                step2_data = all_data['steps']['step2'].get('form_data', {})
                patient_context['age'] = step2_data.get('calculated_age', 'Unknown')
                patient_context['gender'] = step2_data.get('gender', 'Unknown')
            
            if 'step3' in all_data['steps']:
                step3_data = all_data['steps']['step3'].get('form_data', {})
                patient_context['vitals'] = step3_data
        
        # Create AI prompt for medical label extraction
        prompt_template = load_prompt("symptom_analysis")
        prompt = prompt_template.format(
            complaint_text=complaint_text,
            age=patient_context['age'],
            gender=patient_context['gender'],
            vitals=patient_context['vitals']
        )
        
        # Call OpenAI API
        response = call_gpt4(prompt, {})
        print(f"🤖 GPT-4 response received: {len(response) if response else 0} characters")
        
        if not response or response.strip() == "":
            raise Exception("Empty response from AI")
        
        # Clean and parse response
        response = response.strip()
        if response.startswith('```json'):
            response = response[7:]
        if response.endswith('```'):
            response = response[:-3]
        
        # Find JSON boundaries
        start_idx = response.find('{')
        end_idx = response.rfind('}') + 1
        
        if start_idx != -1 and end_idx > start_idx:
            json_str = response[start_idx:end_idx]
            insights_data = json.loads(json_str)
        else:
            raise ValueError("No valid JSON found in response")
        
        # Validate and ensure required fields
        if not isinstance(insights_data, dict):
            raise ValueError("Invalid JSON structure")
        
        insights_data.setdefault('medical_labels', [])
        insights_data.setdefault('urgency_assessment', {'level': 'moderate', 'reasoning': 'Standard assessment'})
        insights_data.setdefault('key_insights', [])
        insights_data.setdefault('symptom_summary', {'primary_concern': 'Symptom analysis'})
        
        print(f"✅ Analysis complete: {len(insights_data.get('medical_labels', []))} labels extracted")
        
        return jsonify({
            'success': True,
            'insights': insights_data,
            'message': 'Quick symptom analysis completed'
        })
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON parsing error: {str(e)}")
        # Return fallback insights
        fallback_insights = {
            'medical_labels': [
                {
                    'label': 'Patient Complaint',
                    'confidence': 50,
                    'category': 'symptom',
                    'severity': 'moderate',
                    'description': 'Symptoms as described by patient'
                }
            ],
            'urgency_assessment': {
                'level': 'moderate',
                'reasoning': 'Standard assessment pending detailed analysis',
                'immediate_concerns': []
            },
            'key_insights': [
                'Symptom analysis requires further evaluation',
                'Professional medical assessment recommended'
            ],
            'symptom_summary': {
                'primary_concern': complaint_text[:100] if complaint_text else 'Patient symptoms',
                'affected_systems': ['To be determined'],
                'duration_significance': 'Requires detailed history',
                'next_steps': 'Complete detailed symptom questionnaire'
            }
        }
        return jsonify({
            'success': True,
            'insights': fallback_insights,
            'fallback': True,
            'message': 'Basic symptom analysis completed'
        })
        
    except Exception as e:
        print(f"❌ Error in quick symptom analysis: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Analysis failed: {str(e)}'
        })

@app.route('/save_step5', methods=['POST'])
def save_step5():
    try:
        print("✅ Starting save_step5")
        
        if not validate_session_step(4):
            return jsonify({'success': False, 'error': 'Please complete step 4 first'})
        
        # Check if this is a modification
        existing_step5 = get_step_data(5)
        is_modification = bool(existing_step5)
        
        # Collect form data
        form_data = {}
        complaint_fields = [
            'primary_complaint', 'complaint_description', 'symptom_duration',
            'pain_level', 'additional_symptoms', 'complaint_text'
        ]
        
        for field in complaint_fields:
            value = request.form.get(field, '')
            if value and value.strip():
                form_data[field] = value.strip()
        
        # Collect AI-generated insights if available
        ai_data = {}
        
        # Include abnormal findings from step4 in step5 data
        all_data = get_all_patient_data()
        abnormal_findings = []
        if 'steps' in all_data and 'step4' in all_data['steps']:
            step4_ai_data = all_data['steps']['step4'].get('ai_generated_data', {})
            generated_questions_str = step4_ai_data.get('generated_questions', '[]')
            
            try:
                if isinstance(generated_questions_str, str):
                    generated_questions = json.loads(generated_questions_str)
                else:
                    generated_questions = generated_questions_str
                
                # Use a set to track unique findings and avoid duplicates
                unique_findings = {}
                
                # Extract unique abnormal findings
                for question_data in generated_questions:
                    if isinstance(question_data, dict) and 'abnormal_finding' in question_data:
                        finding_key = question_data.get('abnormal_finding', '').lower().strip()
                        if finding_key and finding_key not in unique_findings:
                            unique_findings[finding_key] = {
                                'finding': question_data.get('abnormal_finding', ''),
                                'concern': question_data.get('medical_concern', ''),
                                'priority': question_data.get('priority', 'normal')
                            }
                
                # Convert to list
                abnormal_findings = list(unique_findings.values())
                
                print(f"✅ Including {len(abnormal_findings)} unique abnormal findings from step4 in step5 data")
                
            except Exception as e:
                print(f"⚠️ Error parsing step4 findings: {e}")
                abnormal_findings = []
                
                ai_data['abnormal_findings'] = abnormal_findings
                print(f"📊 Included {len(abnormal_findings)} abnormal findings from step4")
            except Exception as e:
                print(f"⚠️ Error parsing step4 abnormal findings: {e}")
        
        # Check if insights were generated and include them
        insights_json = request.form.get('symptom_insights', '')
        if insights_json:
            try:
                insights_data = json.loads(insights_json)
                ai_data['symptom_insights'] = insights_data
                ai_data['insights_generated_at'] = datetime.now().isoformat()
                print(f"🤖 AI insights included: {len(insights_data.get('medical_labels', []))} labels")
            except json.JSONDecodeError:
                print("⚠️ Could not parse symptom insights JSON")
        
        # Collect follow-up question answers from step 4
        followup_answers = {}
        
        for key in request.form.keys():
            if key.startswith('followup_answer_'):
                question_id = key.replace('followup_answer_', '')
                answer = request.form.get(key, '').strip()
                if answer:
                    followup_answers[question_id] = {
                        'answer': answer,
                        'answered_at': datetime.now().isoformat(),
                        'step': 5
                    }
        
        if followup_answers:
            ai_data['followup_answers'] = followup_answers
            print(f"📝 Follow-up answers collected: {len(followup_answers)}")
        
        print(f"📋 Complaints data collected: {len(form_data)} fields")
        print(f"🤖 AI data collected: {len(ai_data)} sections")
        
        # Use step-based save function
        success = save_step_based_patient_data(
            step_number=5,
            form_data=form_data,
            ai_data=ai_data,
            files_data={}
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save complaints data'})
        
        # If modification, invalidate downstream steps
        if is_modification:
            invalidate_downstream_steps(5)
        
        # Update session
        if 'patient_data' not in session:
            session['patient_data'] = {}
        session['patient_data']['step_completed'] = 5
        session.modified = True
        
        print("✅ Step 5 saved successfully with AI data")
        
        return jsonify({
            'success': True,
            'message': 'Complaints and symptoms saved successfully',
            'redirect_url': '/step6',
            'form_fields': len(form_data),
            'ai_insights': len(ai_data),
            'followup_answers': len(followup_answers)
        })
        
    except Exception as e:
        print(f"❌ Error in save_step5: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to save step 5: {str(e)}'})

# Step 6: Complaint Analysis
@app.route('/step6')
def step6():
    if not validate_session_step(5):
        return redirect('/')
    return render_template('step6.html', current_step='step6')

@app.route('/save_step6', methods=['POST'])
def save_step6():
    try:
        print("✅ Starting save_step6")
        
        if not validate_session_step(5):
            return jsonify({'success': False, 'error': 'Please complete step 5 first'})
        
        # This step is mainly AI-generated analysis
        # Collect any user selections or confirmations
        form_data = {}
        
        # Collect analysis results and user confirmations
        analysis_fields = [
            'selected_analysis', 'user_confirmation', 'additional_notes'
        ]
        
        for field in analysis_fields:
            value = request.form.get(field, '')
            if value and value.strip():
                form_data[field] = value.strip()
        
        # AI analysis data would be generated here
        ai_data = {}
        if request.form.get('ai_analysis_results'):
            ai_data['complaint_analysis'] = request.form.get('ai_analysis_results')
        
        print(f"📋 Analysis data collected: {len(form_data)} fields")
        
        # Use step-based save function
        success = save_step_based_patient_data(
            step_number=6,
            form_data=form_data,
            ai_data=ai_data,
            files_data={}
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save analysis data'})
        
        # Update session
        if 'patient_data' not in session:
            session['patient_data'] = {}
        session['patient_data']['step_completed'] = 6
        session.modified = True
        
        print("✅ Step 6 saved successfully")
        
        return jsonify({
            'success': True,
            'message': 'Complaint analysis saved successfully',
            'redirect_url': '/report',
            'form_fields': len(form_data),
            'ai_analysis': len(ai_data)
        })
        
    except Exception as e:
        print(f"❌ Error in save_step6: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to save step 6: {str(e)}'})

@app.route('/save_question_responses', methods=['POST'])
def save_question_responses():
    """Save responses to follow-up questions from step 6 with complete question data"""
    try:
        print("✅ Starting save_question_responses")
        
        if not validate_session_step(5):
            return jsonify({'success': False, 'error': 'Please complete step 5 first'})
        
        data = request.get_json()
        responses = data.get('responses', {})
        original_questions = data.get('original_questions', [])
        analysis_data = data.get('analysis_data', {})
        
        print(f"📝 Received {len(responses)} question responses")
        print(f"📋 Received {len(original_questions)} original questions")
        
        # Prepare comprehensive responses data for storage
        responses_data = {
            'question_responses': responses,
            'original_questions': original_questions,
            'analysis_metadata': analysis_data,
            'total_questions_generated': len(original_questions),
            'total_questions_answered': len(responses),
            'completion_rate': len(responses) / len(original_questions) if original_questions else 0,
            'completed_at': datetime.now().isoformat(),
            'session_data': {
                'questions_generated_from': {
                    'step3_vitals': True,
                    'step4_followups': True,
                    'step5_symptoms': True
                },
                'priority_distribution': {
                    'step5_priority': 0.8,
                    'step3_step4_priority': 0.2
                }
            }
        }
        
        # Also prepare organized Q&A pairs for easy access
        qa_pairs = []
        for response_index, response_data in responses.items():
            qa_pair = {
                'question_index': int(response_index),
                'question_text': response_data.get('question', ''),
                'question_category': response_data.get('category', ''),
                'answer': response_data.get('answer_value', ''),
                'answered_at': response_data.get('timestamp', ''),
                'original_question_data': original_questions[int(response_index)] if int(response_index) < len(original_questions) else {}
            }
            qa_pairs.append(qa_pair)
        
        responses_data['organized_qa_pairs'] = qa_pairs
        
        # Update step 6 data with comprehensive responses
        success = save_step_based_patient_data(
            step_number=6,
            form_data={
                'question_responses_completed': True,
                'questions_answered': len(responses),
                'questions_generated': len(original_questions)
            },
            ai_data=responses_data,
            files_data={}
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save question responses'})
        
        # Update session to mark step 6 as completed
        if 'patient_data' not in session:
            session['patient_data'] = {}
        session['patient_data']['step_completed'] = 6
        session.modified = True
        
        print("✅ Question responses and questions saved successfully")
        print(f"   📊 Questions generated: {len(original_questions)}")
        print(f"   📝 Questions answered: {len(responses)}")
        print(f"   📈 Completion rate: {len(responses)/len(original_questions)*100:.1f}%")
        
        # Generate clinical summary for popup
        print("🏥 Generating clinical summary...")
        summary_result = generate_clinical_summary()
        clinical_summary = ""
        summary_success = False
        
        if summary_result and summary_result.get("success"):
            clinical_summary = summary_result.get("clinical_summary", "")
            summary_success = True
            print(f"✅ Clinical summary generated successfully: {len(clinical_summary)} characters")
        else:
            print(f"❌ Clinical summary generation failed: {summary_result}")
            clinical_summary = "Clinical summary could not be generated at this time."
        
        return jsonify({
            'success': True,
            'message': 'Question responses saved successfully',
            'show_summary': True,  # Always show summary popup
            'clinical_summary': clinical_summary,
            'summary_generated': summary_success,
            'data': {
                'responses_count': len(responses),
                'questions_count': len(original_questions),
                'completion_rate': len(responses) / len(original_questions) if original_questions else 0,
                'redirect_url': '/report'
            }
        })
        
    except Exception as e:
        print(f"❌ Error in save_question_responses: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to save responses: {str(e)}'})

@app.route('/save_clinical_summary', methods=['POST'])
def save_clinical_summary():
    """Save the clinical summary when user clicks Complete Assessment in the popup"""
    try:
        print("✅ Starting save_clinical_summary")
        
        if not validate_session_step(5):
            return jsonify({'success': False, 'error': 'Please complete step 5 first'})
        
        data = request.get_json()
        clinical_summary = data.get('clinical_summary', '')
        
        if not clinical_summary:
            return jsonify({'success': False, 'error': 'No clinical summary provided'})
        
        print(f"📝 Received clinical summary: {len(clinical_summary)} characters")
        
        # Prepare clinical summary data for storage
        clinical_summary_data = {
            'clinical_summary': clinical_summary,
            'summary_accepted_at': datetime.now().isoformat(),
            'assessment_completed': True,
            'final_review_status': 'completed',
            'user_action': 'clicked_complete_assessment'
        }
        
        # Update step 6 data with clinical summary
        success = save_step_based_patient_data(
            step_number=6,
            form_data={
                'assessment_completed': True,
                'clinical_summary_saved': True,
                'final_completion_timestamp': datetime.now().isoformat()
            },
            ai_data=clinical_summary_data,
            files_data={}
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save clinical summary'})
        
        # Update session to mark assessment as fully completed
        if 'patient_data' not in session:
            session['patient_data'] = {}
        session['patient_data']['assessment_completed'] = True
        session['patient_data']['clinical_summary_saved'] = True
        session.modified = True
        
        print("✅ Clinical summary saved successfully to step6 data")
        print(f"   📝 Summary length: {len(clinical_summary)} characters")
        print(f"   ⏰ Saved at: {datetime.now().isoformat()}")
        
        return jsonify({
            'success': True,
            'message': 'Clinical summary saved successfully',
            'data': {
                'summary_length': len(clinical_summary),
                'saved_at': datetime.now().isoformat(),
                'assessment_status': 'completed'
            }
        })
        
    except Exception as e:
        print(f"❌ Error in save_clinical_summary: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to save clinical summary: {str(e)}'})

@app.route('/step7')
def step7():
    """Step 7: ICD11 Code Generation and Analysis"""
    if not validate_session_step(6):
        return redirect('/')
    return render_template('step7.html', current_step='step7')

@app.route('/get_clinical_summary', methods=['GET'])
def get_clinical_summary():
    """Retrieve the clinical summary from step6 data"""
    try:
        print("✅ Getting clinical summary from step6 data")
        
        if not validate_session_step(6):
            return jsonify({'success': False, 'error': 'Please complete step 6 first'})
        
        # Load patient data and get clinical summary from step6
        patient_data = load_patient_data()
        if not patient_data:
            return jsonify({'success': False, 'error': 'No patient data found'})
        
        step6_data = patient_data.get('step6', {})
        ai_data = step6_data.get('ai_generated_data', {})
        
        # Look for clinical summary in the AI data
        clinical_summary = ai_data.get('clinical_summary', '')
        
        if not clinical_summary:
            return jsonify({'success': False, 'error': 'No clinical summary found in step6 data'})
        
        print(f"✅ Clinical summary retrieved: {len(clinical_summary)} characters")
        
        return jsonify({
            'success': True,
            'clinical_summary': clinical_summary,
            'data': {
                'summary_length': len(clinical_summary),
                'retrieved_at': datetime.now().isoformat()
            }
        })
        
    except Exception as e:
        print(f"❌ Error in get_clinical_summary: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to retrieve clinical summary: {str(e)}'})

@app.route('/get_patient_data_summary', methods=['GET'])
def get_patient_data_summary():
    """Get a comprehensive summary of all patient data for differential questioning"""
    try:
        print("📊 Generating patient data summary for differential questioning")
        
        if not validate_session_step(6):
            return jsonify({'success': False, 'error': 'Please complete step 6 first'})
        
        patient_data = load_patient_data()
        if not patient_data:
            return jsonify({'success': False, 'error': 'No patient data found'})
        
        summary_parts = []
        
        # Step 1: Symptoms
        step1_data = patient_data.get('step1', {})
        if step1_data:
            symptoms = step1_data.get('symptoms', {})
            if symptoms:
                symptom_list = []
                for symptom, details in symptoms.items():
                    severity = details.get('severity', 'N/A')
                    symptom_list.append(f'{symptom} (severity: {severity})')
                summary_parts.append(f"Symptoms: {', '.join(symptom_list)}")
        
        # Step 2: Vitals
        step2_data = patient_data.get('step2', {})
        if step2_data:
            vitals_text = []
            for key, value in step2_data.items():
                if key != 'timestamp' and value:
                    vitals_text.append(f"{key}: {value}")
            if vitals_text:
                summary_parts.append(f"Vitals: {', '.join(vitals_text)}")
        
        # Step 3: Medical History
        step3_data = patient_data.get('step3', {})
        if step3_data:
            history_text = []
            for key, value in step3_data.items():
                if key != 'timestamp' and value:
                    if isinstance(value, list):
                        history_text.append(f"{key}: {', '.join(value)}")
                    else:
                        history_text.append(f"{key}: {value}")
            if history_text:
                summary_parts.append(f"Medical History: {', '.join(history_text)}")
        
        # Step 4: Physical Examination  
        step4_data = patient_data.get('step4', {})
        if step4_data:
            exam_text = []
            for key, value in step4_data.items():
                if key != 'timestamp' and value:
                    exam_text.append(f"{key}: {value}")
            if exam_text:
                summary_parts.append(f"Physical Exam: {', '.join(exam_text)}")
        
        # Step 5: Lab Results
        step5_data = patient_data.get('step5', {})
        if step5_data:
            lab_text = []
            for key, value in step5_data.items():
                if key not in ['timestamp', 'test_results'] and value:
                    lab_text.append(f"{key}: {value}")
            
            # Add specific test results
            test_results = step5_data.get('test_results', {})
            if test_results:
                for test, result in test_results.items():
                    lab_text.append(f"{test}: {result}")
            
            if lab_text:
                summary_parts.append(f"Laboratory Results: {', '.join(lab_text)}")
        
        comprehensive_summary = "; ".join(summary_parts) if summary_parts else "No comprehensive patient data available"
        
        print(f"✅ Generated patient data summary: {len(comprehensive_summary)} characters")
        
        return jsonify({
            'success': True,
            'patient_data_summary': comprehensive_summary,
            'data': {
                'summary_length': len(comprehensive_summary),
                'steps_included': list(patient_data.keys()),
                'generated_at': datetime.now().isoformat()
            }
        })
        
    except Exception as e:
        print(f"❌ Error in get_patient_data_summary: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to generate patient data summary: {str(e)}'})

@app.route('/generate_diagnostic_tests', methods=['POST'])
def generate_diagnostic_tests():
    """Generate diagnostic test recommendations based on narrowed ICD codes"""
    try:
        print("🧪 Starting diagnostic tests generation")
        
        data = request.get_json()
        narrowed_icd_codes = data.get('icd_codes', [])
        clinical_summary = data.get('clinical_summary', '')
        patient_data_summary = data.get('patient_data_summary', '')
        elimination_history = data.get('elimination_history', [])
        
        if not narrowed_icd_codes:
            return jsonify({'success': False, 'error': 'No ICD codes provided for diagnostic test generation'})
        
        print(f"🔍 Generating diagnostic tests for {len(narrowed_icd_codes)} ICD codes")
        
        # Generate diagnostic tests using LLM
        tests_result = generate_diagnostic_tests_with_llm(
            narrowed_icd_codes, clinical_summary, patient_data_summary, elimination_history
        )
        
        if not tests_result or not tests_result.get('success'):
            return jsonify({'success': False, 'error': 'Failed to generate diagnostic tests recommendations'})
        
        print("✅ Diagnostic tests generated successfully")
        
        return jsonify({
            'success': True,
            'diagnostic_tests': tests_result.get('diagnostic_tests', []),
            'priority_tests': tests_result.get('priority_tests', []),
            'reasoning': tests_result.get('reasoning', ''),
            'estimated_timeline': tests_result.get('estimated_timeline', ''),
            'cost_considerations': tests_result.get('cost_considerations', ''),
            'clinical_notes': tests_result.get('clinical_notes', '')
        })
        
    except Exception as e:
        print(f"❌ Error in generate_diagnostic_tests: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to generate diagnostic tests: {str(e)}'})

def generate_diagnostic_tests_with_llm(icd_codes, clinical_summary, patient_data_summary, elimination_history):
    """Generate diagnostic test recommendations using LLM based on ICD codes"""
    try:
        print("🤖 Generating diagnostic tests with LLM")
        
        # Format ICD codes for prompt
        codes_text = "\n".join([f"- {code['code']}: {code['title']} (Confidence: {code['confidence']}%)" for code in icd_codes])
        
        # Format elimination history for context
        history_text = ""
        if elimination_history:
            history_text = "\nDifferential diagnosis history:\n" + "\n".join([
                f"- Eliminated {item['eliminated_code']} based on: {item['answer']} (Reasoning: {item['reasoning']})" 
                for item in elimination_history
            ])
        
        prompt_template = load_prompt("diagnostic_tests")
        prompt = prompt_template.format(
            clinical_summary=clinical_summary,
            patient_data_summary=patient_data_summary,
            codes_text=codes_text,
            history_text=history_text
        )

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": load_prompt("diagnostic_tests_system")},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000,
            temperature=0.3
        )
        
        result_text = response.choices[0].message.content.strip()
        print(f"🔍 Raw diagnostic tests response: {result_text[:200]}...")
        
        # Clean the response to ensure it's valid JSON
        if not result_text.startswith('{'):
            start = result_text.find('{')
            end = result_text.rfind('}') + 1
            if start != -1 and end != -1:
                result_text = result_text[start:end]
        
        try:
            result = json.loads(result_text)
        except json.JSONDecodeError as e:
            print(f"❌ JSON decode error: {e}")
            print(f"📄 Full response text: {result_text}")
            return {'success': False, 'error': 'Invalid JSON response from AI'}
        
        if not result.get('success'):
            print(f"❌ LLM returned success=False: {result}")
            return {'success': False, 'error': result.get('error', 'Unknown AI error')}
        
        diagnostic_tests = result.get('diagnostic_tests', [])
        print(f"✅ Generated {len(diagnostic_tests)} diagnostic test recommendations")
        
        return result
        
    except Exception as e:
        print(f"❌ Error generating diagnostic tests: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

@app.route('/test_icd_endpoint', methods=['GET', 'POST'])
def test_icd_endpoint():
    """Test endpoint to verify connectivity"""
    print("🔧 TEST ENDPOINT CALLED!")
    print(f"Method: {request.method}")
    print(f"Content-Type: {request.content_type}")
    if request.method == 'POST':
        data = request.get_json()
        print(f"Data received: {data}")
    return jsonify({'success': True, 'message': 'Test endpoint working!'})

@app.route('/generate_icd_codes', methods=['POST'])
def generate_icd_codes():
    """Generate ICD11 codes based on clinical summary"""
    try:
        print("✅ Starting ICD11 code generation with LLM - DEBUG MODE")
        print(f"🔍 Request method: {request.method}")
        print(f"🔍 Request content type: {request.content_type}")
        
        if not validate_session_step(6):
            print("❌ Session validation failed - step 6 not completed")
            return jsonify({'success': False, 'error': 'Please complete step 6 first'})
        
        print("✅ Session validation passed")
        
        data = request.get_json()
        print(f"🔍 Received data: {data}")
        
        if not data:
            print("❌ No JSON data received")
            return jsonify({'success': False, 'error': 'No data received'})
            
        clinical_summary = data.get('clinical_summary', '')
        print(f"📝 Clinical summary length: {len(clinical_summary)}")
        
        if not clinical_summary:
            print("❌ No clinical summary provided")
            return jsonify({'success': False, 'error': 'No clinical summary provided'})
        
        print(f"📝 Generating ICD codes for summary: {len(clinical_summary)} characters")
        
        # Get all patient data for comprehensive analysis
        print("📂 Loading patient data...")
        patient_data = load_patient_data()
        if not patient_data:
            print("❌ No patient data available")
            return jsonify({'success': False, 'error': 'No patient data available'})
        
        print(f"✅ Patient data loaded: {len(patient_data)} sections")
        
        # Generate ICD11 codes using LLM
        print("🤖 Calling LLM for ICD code generation...")
        icd_result = generate_icd11_codes_with_llm(clinical_summary, patient_data)
        
        if not icd_result or not icd_result.get('success'):
            print(f"❌ LLM generation failed: {icd_result}")
            return jsonify({'success': False, 'error': 'Failed to generate ICD codes - LLM error'})
        
        icd_codes = icd_result.get('icd_codes', [])
        
        # Save the generated ICD codes to step7 data
        icd_data = {
            'icd_codes_generated': True,
            'icd_codes': icd_codes,
            'clinical_summary_used': clinical_summary,
            'generation_timestamp': datetime.now().isoformat(),
            'total_codes_generated': len(icd_codes),
            'llm_analysis': icd_result.get('analysis_notes', '')
        }
        
        # Save to step7
        success = save_step_based_patient_data(
            step_number=7,
            form_data={
                'icd_generation_completed': True,
                'codes_generated': len(icd_codes)
            },
            ai_data=icd_data,
            files_data={}
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save ICD codes'})
        
        print(f"✅ ICD11 codes generated and saved: {len(icd_codes)} codes")
        
        return jsonify({
            'success': True,
            'icd_codes': icd_codes,
            'analysis_notes': icd_result.get('analysis_notes', ''),
            'data': {
                'codes_count': len(icd_codes),
                'generated_at': datetime.now().isoformat(),
                'summary_length': len(clinical_summary)
            }
        })
        
    except Exception as e:
        print(f"❌ Error in generate_icd_codes: {str(e)}")
        import traceback
        print("📄 Full traceback:")
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to generate ICD codes: {str(e)}'})

@app.route('/generate_differential_question', methods=['POST'])
def generate_differential_question():
    """Generate a differential question to eliminate one ICD code"""
    try:
        print("🔍 Starting differential question generation")
        
        data = request.get_json()
        remaining_icd_codes = data.get('icd_codes', [])
        clinical_summary = data.get('clinical_summary', '')
        patient_data_summary = data.get('patient_data_summary', '')
        elimination_history = data.get('elimination_history', [])
        
        if len(remaining_icd_codes) <= 2:
            return jsonify({
                'success': False, 
                'error': 'Cannot eliminate more codes. Already at target of 2 codes.'
            })
        
        print(f"📊 Generating question for {len(remaining_icd_codes)} remaining codes")
        
        # Generate differential question using LLM
        question_result = generate_differential_question_with_llm(
            remaining_icd_codes, clinical_summary, patient_data_summary, elimination_history
        )
        
        if not question_result or not question_result.get('success'):
            return jsonify({'success': False, 'error': 'Failed to generate differential question'})
        
        print("✅ Differential question generated successfully")
        
        return jsonify({
            'success': True,
            'question': question_result.get('question'),
            'target_code_to_eliminate': question_result.get('target_code_to_eliminate'),
            'reasoning': question_result.get('reasoning'),
            'answer_options': question_result.get('answer_options', [])
        })
        
    except Exception as e:
        print(f"❌ Error in generate_differential_question: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to generate question: {str(e)}'})

@app.route('/process_differential_answer', methods=['POST'])
def process_differential_answer():
    """Process the answer and eliminate the appropriate ICD code"""
    try:
        print("🔄 Processing differential answer")
        
        data = request.get_json()
        answer = data.get('answer')
        remaining_icd_codes = data.get('icd_codes', [])
        target_code_to_eliminate = data.get('target_code_to_eliminate')
        question = data.get('question')
        clinical_summary = data.get('clinical_summary', '')
        
        print(f"📝 Answer: {answer}")
        print(f"🎯 Target to eliminate: {target_code_to_eliminate}")
        print(f"📊 Current codes count: {len(remaining_icd_codes)}")
        print(f"📋 Current codes: {[code['code'] for code in remaining_icd_codes]}")
        
        # Validate we have codes to eliminate
        if len(remaining_icd_codes) <= 2:
            return jsonify({
                'success': False, 
                'error': 'Already at target of 2 or fewer codes. Cannot eliminate more.'
            })
        
        # Use LLM to determine which code to eliminate
        elimination_result = process_answer_with_llm(
            answer, question, remaining_icd_codes, target_code_to_eliminate, clinical_summary
        )
        
        if not elimination_result or not elimination_result.get('success'):
            return jsonify({'success': False, 'error': 'Failed to process answer'})
        
        eliminated_code = elimination_result.get('eliminated_code', '').strip()
        reasoning = elimination_result.get('reasoning', '')
        
        print(f"🎯 Code to eliminate: '{eliminated_code}'")
        
        # Validate eliminated code exists in current list
        current_codes = [code['code'] for code in remaining_icd_codes]
        if eliminated_code not in current_codes:
            print(f"❌ Error: Code '{eliminated_code}' not found in current codes {current_codes}")
            return jsonify({
                'success': False, 
                'error': f'Invalid elimination: Code {eliminated_code} not in current list'
            })
        
        # Remove the eliminated code from the list
        updated_codes = [code for code in remaining_icd_codes if code['code'] != eliminated_code]
        
        print(f"✅ Eliminated code: {eliminated_code}")
        print(f"📊 Updated codes count: {len(updated_codes)}")
        print(f"📋 Updated codes: {[code['code'] for code in updated_codes]}")
        
        # Verify elimination actually happened
        if len(updated_codes) != len(remaining_icd_codes) - 1:
            print(f"❌ Elimination failed! Expected {len(remaining_icd_codes) - 1} codes, got {len(updated_codes)}")
            return jsonify({
                'success': False,
                'error': f'Elimination verification failed. Expected {len(remaining_icd_codes) - 1} codes, got {len(updated_codes)}'
            })
        
        return jsonify({
            'success': True,
            'eliminated_code': eliminated_code,
            'updated_icd_codes': updated_codes,
            'reasoning': reasoning,
            'remaining_count': len(updated_codes),
            'verification': {
                'original_count': len(remaining_icd_codes),
                'final_count': len(updated_codes),
                'eliminated_successfully': True
            }
        })
        
    except Exception as e:
        print(f"❌ Error in process_differential_answer: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to process answer: {str(e)}'})

def generate_differential_question_with_llm(icd_codes, clinical_summary, patient_data_summary, elimination_history):
    """Generate a targeted differential question to eliminate one specific ICD code"""
    try:
        print("🤖 Generating differential question with LLM")
        
        # Format ICD codes for prompt
        codes_text = "\n".join([f"- {code['code']}: {code['title']} (Confidence: {code['confidence']}%)" for code in icd_codes])
        current_codes = [code['code'] for code in icd_codes]
        
        # Format elimination history
        history_text = ""
        eliminated_codes = []
        if elimination_history:
            eliminated_codes = [item.get('eliminated_code', '') for item in elimination_history if item.get('eliminated_code')]
            history_text = "Previously eliminated codes:\n" + "\n".join([f"- {item['eliminated_code']}: {item['reasoning']}" for item in elimination_history if item.get('eliminated_code')])
        
        print(f"🔍 Current available codes: {current_codes}")
        print(f"🔍 Previously eliminated codes: {eliminated_codes}")
        
        prompt_template = load_prompt("differential_question")
        prompt = prompt_template.format(
            clinical_summary=clinical_summary,
            patient_data_summary=patient_data_summary,
            codes_text=codes_text,
            history_text=history_text,
            current_codes=', '.join(current_codes),
            eliminated_codes=', '.join(eliminated_codes) if eliminated_codes else 'None eliminated yet'
        )

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": load_prompt("differential_question_system")},
                {"role": "user", "content": prompt}
            ],
            max_tokens=1000,
            temperature=0.2
        )
        
        result_text = response.choices[0].message.content.strip()
        print(f"🔍 Raw LLM response: {result_text}")
        
        # Clean the response to ensure it's valid JSON
        if not result_text.startswith('{'):
            start = result_text.find('{')
            end = result_text.rfind('}') + 1
            if start != -1 and end != -1:
                result_text = result_text[start:end]
        
        result = json.loads(result_text)
        target_code = result.get('target_code_to_eliminate', '').strip()
        
        print(f"🔍 Parsed target_code: '{target_code}'")
        
        # Validate the target code exists in current list
        if not target_code or target_code not in current_codes:
            print(f"❌ Invalid target code: '{target_code}' not in {current_codes}")
            # Fallback: target the first available code
            target_code = current_codes[0] if current_codes else ''
            result['target_code_to_eliminate'] = target_code
            result['reasoning'] = f"Fallback targeting due to invalid LLM response"
            print(f"🔧 Fallback: Targeting '{target_code}'")
        
        print(f"✅ Generated question targeting: {result.get('target_code_to_eliminate')}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error generating differential question: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

def process_answer_with_llm(answer, question, icd_codes, target_code_to_eliminate, clinical_summary):
    """Process the user's answer and determine which ICD code to eliminate"""
    try:
        print("🤖 Processing answer with LLM")
        
        codes_text = "\n".join([f"- {code['code']}: {code['title']}" for code in icd_codes])
        current_codes = [code['code'] for code in icd_codes]
        
        print(f"🔍 Current codes available: {current_codes}")
        print(f"🎯 Target code to eliminate: {target_code_to_eliminate}")
        
        prompt_template = load_prompt("answer_processing")
        prompt = prompt_template.format(
            clinical_summary=clinical_summary,
            codes_text=codes_text,
            question=question,
            answer=answer,
            target_code_to_eliminate=target_code_to_eliminate,
            current_codes=', '.join(current_codes)
        )

        response = openai_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": load_prompt("answer_processing_system")},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.1
        )
        
        result_text = response.choices[0].message.content.strip()
        print(f"🔍 Raw LLM response: {result_text}")
        
        # Clean the response to ensure it's valid JSON
        if not result_text.startswith('{'):
            # Find the JSON part if there's extra text
            start = result_text.find('{')
            end = result_text.rfind('}') + 1
            if start != -1 and end != -1:
                result_text = result_text[start:end]
        
        result = json.loads(result_text)
        eliminated_code = result.get('eliminated_code', '').strip()
        
        print(f"🔍 Parsed eliminated_code: '{eliminated_code}'")
        
        # Validate the eliminated code exists in current list
        if not eliminated_code or eliminated_code not in current_codes:
            print(f"❌ Invalid eliminated code: '{eliminated_code}' not in {current_codes}")
            # Fallback: eliminate the target code or the last code
            if target_code_to_eliminate and target_code_to_eliminate in current_codes:
                eliminated_code = target_code_to_eliminate
                result['eliminated_code'] = eliminated_code
                result['reasoning'] = f"Fallback elimination of target code due to invalid LLM response"
                print(f"🔧 Fallback: Eliminating target code '{eliminated_code}'")
            else:
                # Last resort: eliminate the last code in the list
                eliminated_code = current_codes[-1]
                result['eliminated_code'] = eliminated_code  
                result['reasoning'] = f"Emergency fallback elimination due to LLM error"
                print(f"🚨 Emergency fallback: Eliminating last code '{eliminated_code}'")
        
        print(f"✅ Final decision: Eliminate {eliminated_code}")
        
        return result
        
    except Exception as e:
        print(f"❌ Error processing answer: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Emergency fallback if everything fails
        if icd_codes and len(icd_codes) > 0:
            fallback_code = icd_codes[-1]['code']
            print(f"🚨 Complete fallback: Eliminating {fallback_code}")
            return {
                "success": True,
                "eliminated_code": fallback_code,
                "reasoning": "Emergency elimination due to system error"
            }
        
        return None

def generate_icd11_codes_with_llm(clinical_summary, patient_data):
    """Generate ICD11 codes using LLM API based on WHO official codes"""
    try:
        print("🤖 Generating ICD11 codes with LLM...")
        print(f"📝 Input summary length: {len(clinical_summary)}")
        print(f"📊 Patient data keys: {list(patient_data.keys())}")
        
        # Extract relevant data from patient data
        symptoms_data = patient_data.get('step1', {})
        vitals_data = patient_data.get('step2', {})
        followup_data = patient_data.get('step4', {})
        
        # Build comprehensive context for LLM
        context = f"""
Clinical Summary:
{clinical_summary}

Primary Symptoms:
- Chief Complaint: {symptoms_data.get('complaint_text', 'Not specified')}
- Duration: {symptoms_data.get('symptom_duration', 'Not specified')}
- Pain Level: {symptoms_data.get('pain_level', 'Not specified')}

Vital Signs:
- Temperature: {vitals_data.get('temperature', 'Not recorded')} {vitals_data.get('temperature_unit', '')}
- Oxygen Saturation: {vitals_data.get('oxygen_saturation', 'Not recorded')}%
- Lung Congestion: {vitals_data.get('lung_congestion', 'Not assessed')}

Follow-up Questions Answered: {len(followup_data.get('organized_qa_pairs', []))} questions
"""

        # Create LLM prompt for ICD11 code generation
        prompt_template = load_prompt("icd11_generation")
        prompt = prompt_template.format(context=context)

        # Make API call to OpenAI
        print("🔗 Making OpenAI API call...")
        try:
            # Use the existing openai_client that was configured at startup
            response = openai_client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": load_prompt("icd11_generation_system")},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.3
            )
            print("✅ OpenAI API call successful")
            
            # Process the successful response
            result_text = response.choices[0].message.content.strip()
            print(f"✅ LLM response received: {len(result_text)} characters")
            
            # Parse JSON response
            try:
                result = json.loads(result_text)
                
                # Validate the response structure
                if not result.get('success'):
                    print("❌ LLM returned success=false")
                    return None
                    
                icd_codes = result.get('icd_codes', [])
                if not icd_codes or len(icd_codes) < 5:
                    print(f"❌ Insufficient ICD codes returned: {len(icd_codes)}")
                    return None
                
                # Ensure we have 7-10 codes
                if len(icd_codes) > 10:
                    icd_codes = icd_codes[:10]
                
                print(f"✅ Generated {len(icd_codes)} ICD-11 codes")
                for code in icd_codes[:3]:  # Log first 3 codes
                    print(f"   📋 {code.get('code')}: {code.get('title')} (confidence: {code.get('confidence')}%)")
                
                return {
                    'success': True,
                    'icd_codes': icd_codes,
                    'analysis_notes': result.get('analysis_notes', '')
                }
                
            except json.JSONDecodeError as e:
                print(f"❌ Failed to parse LLM JSON response: {e}")
                print(f"Raw response first 500 chars: {result_text[:500]}...")
                return None
            
        except Exception as api_error:
            print(f"❌ OpenAI API error: {str(api_error)}")
            print("🔄 Using mock data for testing purposes...")
            
            # Return mock ICD codes for testing
            mock_icd_codes = [
                {
                    "code": "8A80.Z",
                    "title": "Acute respiratory infection, unspecified",
                    "description": "An acute infection involving the respiratory system where the specific organism and location are not identified. This matches the patient's fever and breathing difficulties.",
                    "confidence": 92
                },
                {
                    "code": "MG30.0Y",
                    "title": "Fever, unspecified",
                    "description": "Elevated body temperature without identification of the underlying cause. Patient presents with high fever (101°C).",
                    "confidence": 95
                },
                {
                    "code": "MD11.9",
                    "title": "Dyspnoea, unspecified",
                    "description": "Difficulty breathing or shortness of breath without further specification. Correlates with low oxygen saturation (80%).",
                    "confidence": 88
                },
                {
                    "code": "8A81.2",
                    "title": "Upper respiratory tract infection, unspecified",
                    "description": "Infection of the upper respiratory tract without specification of the causative organism.",
                    "confidence": 85
                },
                {
                    "code": "MG30.1",
                    "title": "Pyrexia of unknown origin",
                    "description": "Fever of unknown cause, often associated with systemic infections.",
                    "confidence": 78
                },
                {
                    "code": "MD12.0",
                    "title": "Tachypnoea",
                    "description": "Rapid breathing often associated with respiratory distress or fever.",
                    "confidence": 82
                },
                {
                    "code": "8A84.1",
                    "title": "Viral respiratory tract infection, unspecified",
                    "description": "Viral infection affecting the respiratory tract, commonly presenting with fever and breathing difficulties.",
                    "confidence": 75
                },
                {
                    "code": "MG31.2",
                    "title": "Chills",
                    "description": "Sudden feeling of cold with shivering, often accompanying fever during infections.",
                    "confidence": 90
                }
            ]
            
            return {
                'success': True,
                'icd_codes': mock_icd_codes,
                'analysis_notes': 'Based on the clinical presentation of high fever (101°C), low oxygen saturation (80%), and respiratory symptoms, the most likely diagnoses include acute respiratory infections and fever-related conditions. The patient would benefit from further diagnostic tests including chest X-ray, blood cultures, and complete blood count. (Note: This analysis uses mock data due to API connectivity issues.)'
            }
            
    except Exception as e:
        print(f"❌ Error in generate_icd11_codes_with_llm: {str(e)}")
        import traceback
        print("📄 LLM function traceback:")
        traceback.print_exc()
        return None

@app.route('/complete_assessment', methods=['POST'])
def complete_assessment():
    """Complete the assessment process"""
    try:
        print("✅ Completing assessment")
        
        data = request.get_json()
        step = data.get('step', 7)
        
        # Update final completion status
        completion_data = {
            'assessment_fully_completed': True,
            'completion_step': step,
            'final_completion_timestamp': datetime.now().isoformat(),
            'user_confirmed_completion': True
        }
        
        # Save final completion status
        success = save_step_based_patient_data(
            step_number=step,
            form_data={
                'assessment_fully_completed': True,
                'completion_confirmed': True
            },
            ai_data=completion_data,
            files_data={}
        )
        
        if not success:
            return jsonify({'success': False, 'error': 'Failed to save completion status'})
        
        # Update session
        if 'patient_data' not in session:
            session['patient_data'] = {}
        session['patient_data']['assessment_fully_completed'] = True
        session['patient_data']['highest_step_completed'] = step
        session.modified = True
        
        print("✅ Assessment completed successfully")
        
        return jsonify({
            'success': True,
            'message': 'Assessment completed successfully',
            'data': {
                'completed_at': datetime.now().isoformat(),
                'final_step': step
            }
        })
        
    except Exception as e:
        print(f"❌ Error in complete_assessment: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to complete assessment: {str(e)}'})

@app.route('/generate_icd_diagnosis', methods=['POST'])
def generate_icd_diagnosis():
    """Generate comprehensive ICD disease codes using holistic analysis of steps 4, 5, and 6"""
    try:
        print("✅ ===== STARTING COMPREHENSIVE ICD DIAGNOSIS GENERATION =====")
        
        if not validate_session_step(6):
            return jsonify({'success': False, 'error': 'Please complete step 6 first'})
        
        # Collect data from all relevant steps with specified priorities
        step4_data = get_step_data(4)  # 10% priority (or 40% if no step4 questions)
        step5_data = get_step_data(5)  # 60% priority 
        step6_data = get_step_data(6)  # 30% priority (or 50% if no step4 questions)
        
        print(f"📊 Step 4 data available: {bool(step4_data)}")
        print(f"📊 Step 5 data available: {bool(step5_data)}")
        print(f"📊 Step 6 data available: {bool(step6_data)}")
        
        # Determine priority distribution based on step 4 availability
        step4_questions = []
        if step4_data:
            ai_data = step4_data.get('ai_data', {})
            step4_questions = ai_data.get('generated_questions', [])
        
        has_step4_questions = len(step4_questions) > 0
        
        if has_step4_questions:
            priorities = {'step5': 0.6, 'step6': 0.3, 'step4': 0.1}
            print("📈 Using priority distribution: Step5(60%) + Step6(30%) + Step4(10%)")
        else:
            priorities = {'step5': 0.6, 'step6': 0.4, 'step4': 0.0}
            print("📈 Using priority distribution: Step5(60%) + Step6(40%) + Step4(0%)")
        
        # Generate comprehensive ICD diagnosis
        diagnosis_result = generate_comprehensive_icd_diagnosis(
            step4_data, step5_data, step6_data, priorities
        )
        
        # Save diagnosis data to step 7
        success = save_step_based_patient_data(
            step_number=7,
            form_data={'diagnosis_generated': True},
            ai_data=diagnosis_result,
            files_data={}
        )
        
        if not success:
            print("⚠️ Failed to save diagnosis data, but returning result anyway")
        
        return jsonify({
            'success': True,
            'diagnosis': diagnosis_result
        })
        
    except Exception as e:
        print(f"❌ Error in generate_icd_diagnosis: {str(e)}")
        return jsonify({'success': False, 'error': f'Diagnosis generation failed: {str(e)}'})

def generate_comprehensive_icd_diagnosis(step4_data, step5_data, step6_data, priorities):
    """Generate ICD disease codes using holistic medical analysis"""
    try:
        print("🔬 Starting comprehensive medical analysis...")
        
        # Extract and prioritize data from each step
        clinical_context = build_clinical_context(step4_data, step5_data, step6_data, priorities)
        
        if not clinical_context['has_sufficient_data']:
            print("⚠️ Insufficient clinical data for diagnosis")
            return generate_fallback_icd_diagnosis({})
        
        # Generate AI-powered ICD diagnosis
        icd_diagnosis = generate_ai_icd_diagnosis(clinical_context)
        
        if icd_diagnosis:
            print(f"✅ Generated {len(icd_diagnosis.get('top_diagnoses', []))} ICD diagnoses")
            return icd_diagnosis
        else:
            print("🔄 AI diagnosis failed, using fallback")
            return generate_fallback_icd_diagnosis(clinical_context)
            
    except Exception as e:
        print(f"❌ Error in comprehensive diagnosis generation: {str(e)}")
        return generate_fallback_icd_diagnosis({})

def build_clinical_context(step4_data, step5_data, step6_data, priorities):
    """Build comprehensive clinical context with weighted priorities"""
    try:
        print("📋 Building clinical context...")
        
        context = {
            'has_sufficient_data': False,
            'primary_symptoms': {},
            'follow_up_responses': {},
            'step6_qa_responses': {},
            'ai_insights': {},
            'vital_signs': {},
            'abnormal_findings': [],
            'priorities': priorities,
            'data_sources': []
        }
        
        # Process Step 5 data (60% priority) - Primary symptoms and AI insights
        if step5_data:
            form_data = step5_data.get('form_data', {})
            ai_data = step5_data.get('ai_data', {})
            
            context['primary_symptoms'] = {
                'complaint_text': form_data.get('complaint_text', ''),
                'primary_complaint': form_data.get('primary_complaint', ''),
                'complaint_description': form_data.get('complaint_description', ''),
                'symptom_duration': form_data.get('symptom_duration', ''),
                'pain_level': form_data.get('pain_level', ''),
                'additional_symptoms': form_data.get('additional_symptoms', '')
            }
            
            # AI insights from step 5
            symptom_insights = ai_data.get('symptom_insights', {})
            if symptom_insights:
                context['ai_insights'] = {
                    'medical_labels': symptom_insights.get('medical_labels', []),
                    'confidence_scores': symptom_insights.get('confidence_scores', {}),
                    'insights_metadata': symptom_insights.get('metadata', {})
                }
            
            context['data_sources'].append('step5_symptoms')
            print(f"   ✅ Step 5: Primary symptoms and AI insights extracted")
        
        # Process Step 6 data (30%/40% priority) - Follow-up Q&A responses
        if step6_data:
            ai_data = step6_data.get('ai_data', {})
            
            # Get organized Q&A pairs
            qa_pairs = ai_data.get('organized_qa_pairs', [])
            if qa_pairs:
                context['step6_qa_responses'] = qa_pairs
                print(f"   ✅ Step 6: {len(qa_pairs)} follow-up Q&A responses extracted")
            
            context['data_sources'].append('step6_followup_qa')
        
        # Process Step 4 data (10% priority) - Initial follow-up questions
        if step4_data and priorities['step4'] > 0:
            form_data = step4_data.get('form_data', {})
            ai_data = step4_data.get('ai_data', {})
            
            # Extract follow-up question responses
            followup_responses = {}
            for key, value in form_data.items():
                if key.startswith('followup_answer_'):
                    question_id = key.replace('followup_answer_', '')
                    followup_responses[question_id] = value
            
            if followup_responses:
                context['follow_up_responses'] = followup_responses
                print(f"   ✅ Step 4: {len(followup_responses)} initial follow-up responses extracted")
            
            context['data_sources'].append('step4_initial_followup')
        
        # Get vital signs from step 3 for context
        step3_data = get_step_data(3)
        if step3_data:
            form_data = step3_data.get('form_data', {})
            ai_data = step3_data.get('ai_data', {})
            
            context['vital_signs'] = form_data
            context['abnormal_findings'] = ai_data.get('abnormal_findings', [])
            context['data_sources'].append('step3_vitals')
            print(f"   ✅ Step 3: Vital signs and {len(context['abnormal_findings'])} abnormal findings")
        
        # Determine if we have sufficient data for diagnosis
        has_symptoms = bool(context['primary_symptoms'].get('complaint_text') or 
                           context['primary_symptoms'].get('primary_complaint'))
        has_followup = bool(context['step6_qa_responses'] or context['follow_up_responses'])
        has_ai_insights = bool(context['ai_insights'].get('medical_labels'))
        
        context['has_sufficient_data'] = has_symptoms and (has_followup or has_ai_insights)
        
        print(f"📊 Clinical context summary:")
        print(f"   🎯 Data sources: {', '.join(context['data_sources'])}")
        print(f"   📝 Has symptoms: {has_symptoms}")
        print(f"   🔍 Has follow-up data: {has_followup}")
        print(f"   🤖 Has AI insights: {has_ai_insights}")
        print(f"   ✅ Sufficient for diagnosis: {context['has_sufficient_data']}")
        
        return context
        
    except Exception as e:
        print(f"❌ Error building clinical context: {str(e)}")
        return {'has_sufficient_data': False}

def generate_ai_icd_diagnosis(clinical_context):
    """Generate ICD disease codes using AI with comprehensive clinical context"""
    try:
        print("🤖 Generating AI-powered ICD diagnosis...")
        
        # Build comprehensive prompt for AI diagnosis
        prompt = build_icd_diagnosis_prompt(clinical_context)
        
        if not prompt:
            print("❌ Failed to build diagnosis prompt")
            return None
        
        print(f"📝 Prompt length: {len(prompt)} characters")
        
        # Call OpenAI API for diagnosis
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": load_prompt("icd10_diagnosis_system")
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.3,  # Lower temperature for more accurate medical diagnosis
            max_tokens=2500
        )
        
        ai_response = response.choices[0].message.content.strip()
        print(f"🤖 AI Response received: {len(ai_response)} characters")
        
        # Parse AI response
        try:
            # Extract JSON from response
            json_start = ai_response.find('{')
            json_end = ai_response.rfind('}') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_content = ai_response[json_start:json_end]
                diagnosis_result = json.loads(json_content)
                
                # Validate diagnosis structure
                if validate_diagnosis_result(diagnosis_result):
                    print("✅ AI diagnosis generated and validated successfully")
                    return diagnosis_result
                else:
                    print("❌ AI diagnosis failed validation")
                    return None
                    
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error: {str(e)}")
            print(f"Raw AI response: {ai_response[:300]}...")
            return None
            
    except Exception as e:
        print(f"❌ Error in AI diagnosis generation: {str(e)}")
        return None

def build_icd_diagnosis_prompt(clinical_context):
    """Build comprehensive prompt for AI ICD diagnosis generation"""
    try:
        print("📝 Building ICD diagnosis prompt...")
        
        priorities = clinical_context['priorities']
        data_sources = clinical_context['data_sources']
        
        # Build content for template replacement
        symptoms_data = ""
        symptoms = clinical_context.get('primary_symptoms', {})
        if symptoms:
            symptoms_data = f"""

Chief Complaint: {symptoms.get('complaint_text', 'Not specified')}
Primary Complaint: {symptoms.get('primary_complaint', 'Not specified')}
Detailed Description: {symptoms.get('complaint_description', 'Not specified')}
Duration: {symptoms.get('symptom_duration', 'Not specified')}
Pain Level: {symptoms.get('pain_level', 'Not specified')}
Additional Symptoms: {symptoms.get('additional_symptoms', 'Not specified')}"""
        
        # Add AI insights if available
        ai_insights = ""
        ai_insight_data = clinical_context.get('ai_insights', {})
        if ai_insight_data.get('medical_labels'):
            ai_insights = f"""

AI-IDENTIFIED MEDICAL LABELS:
{', '.join(ai_insight_data['medical_labels'])}

CONFIDENCE SCORES:
{ai_insight_data.get('confidence_scores', {})}"""
        
        # Add Step 6 follow-up Q&A data
        step6_qa_data = ""
        step6_qa = clinical_context.get('step6_qa_responses', [])
        if step6_qa and priorities['step6'] > 0:
            step6_qa_data = f"""

PERSONALIZED FOLLOW-UP RESPONSES (PRIORITY - {priorities['step6']*100:.0f}%):"""
            
            for qa_pair in step6_qa[:10]:  # Limit to avoid token overflow
                question = qa_pair.get('question', '')
                answer = qa_pair.get('answer', '')
                category = qa_pair.get('category', 'general')
                
                if question and answer:
                    step6_qa_data += f"""
[{category.upper()}] Q: {question}
A: {answer}"""
        
        # Add Step 4 initial follow-up data
        step4_followup_data = ""
        step4_responses = clinical_context.get('follow_up_responses', {})
        if step4_responses and priorities['step4'] > 0:
            step4_followup_data = f"""

INITIAL FOLLOW-UP RESPONSES (PRIORITY - {priorities['step4']*100:.0f}%):"""
            
            for question_id, answer in list(step4_responses.items())[:5]:  # Limit responses
                step4_followup_data += f"""
Response {question_id}: {answer}"""
        
        # Add vital signs context
        vital_signs = ""
        vital_signs_data = clinical_context.get('vital_signs', {})
        abnormal_findings = clinical_context.get('abnormal_findings', [])
        
        if vital_signs_data or abnormal_findings:
            vital_signs = f"""

VITAL SIGNS & CLINICAL FINDINGS (CONTEXT):"""
            
            if vital_signs_data:
                height_feet = vital_signs_data.get('height_feet', '')
                height_inches = vital_signs_data.get('height_inches', '')
                vital_signs += f"""
Age: {vital_signs_data.get('age', 'Not specified')}
Gender: {vital_signs_data.get('gender', 'Not specified')}
Blood Pressure: {vital_signs_data.get('systolic_bp', '')}/{vital_signs_data.get('diastolic_bp', '')} mmHg
Heart Rate: {vital_signs_data.get('heart_rate', '')} bpm
Temperature: {vital_signs_data.get('temperature', '')}°F
Respiratory Rate: {vital_signs_data.get('respiratory_rate', '')} breaths/min
Weight: {vital_signs_data.get('weight', '')} lbs
Height: {height_feet}'{height_inches}"
BMI: {vital_signs_data.get('bmi', '')}"""
            
            if abnormal_findings:
                vital_signs += f"""

ABNORMAL FINDINGS IDENTIFIED:
{', '.join(abnormal_findings)}"""
        
        # Patient demographics
        patient_demographics = clinical_context.get('patient_demographics', '')
        
        # Load and format the comprehensive diagnosis prompt
        prompt_template = load_prompt("comprehensive_diagnosis")
        prompt = prompt_template.format(
            step5_priority=priorities['step5']*100,
            step6_priority=priorities['step6']*100,
            step4_priority=priorities['step4']*100,
            data_sources=', '.join(data_sources),
            symptoms_data=symptoms_data,
            ai_insights=ai_insights,
            step6_qa_data=step6_qa_data,
            step4_followup_data=step4_followup_data,
            vital_signs=vital_signs,
            patient_demographics=patient_demographics
        )
        
        print(f"✅ Diagnosis prompt built successfully ({len(prompt)} characters)")
        return prompt
        
    except Exception as e:
        print(f"❌ Error building diagnosis prompt: {str(e)}")
        return None

def validate_diagnosis_result(diagnosis_result):
    """Validate the structure and content of AI diagnosis result"""
    try:
        if not isinstance(diagnosis_result, dict):
            return False
        
        # Check required fields
        required_fields = ['top_diagnoses', 'clinical_summary']
        for field in required_fields:
            if field not in diagnosis_result:
                print(f"❌ Missing required field: {field}")
                return False
        
        # Validate top_diagnoses structure
        top_diagnoses = diagnosis_result.get('top_diagnoses', [])
        if not isinstance(top_diagnoses, list) or len(top_diagnoses) == 0:
            print("❌ top_diagnoses must be a non-empty list")
            return False
        
        # Validate each diagnosis
        for i, diagnosis in enumerate(top_diagnoses):
            if not isinstance(diagnosis, dict):
                print(f"❌ Diagnosis {i} must be a dictionary")
                return False
            
            required_diagnosis_fields = ['icd_code', 'disease_name', 'confidence_percentage']
            for field in required_diagnosis_fields:
                if field not in diagnosis:
                    print(f"❌ Diagnosis {i} missing field: {field}")
                    return False
            
            # Validate ICD code format (basic check)
            icd_code = diagnosis.get('icd_code', '')
            if not icd_code or len(icd_code) < 3:
                print(f"❌ Invalid ICD code format: {icd_code}")
                return False
            
            # Validate confidence percentage
            confidence = diagnosis.get('confidence_percentage')
            if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 100:
                print(f"❌ Invalid confidence percentage: {confidence}")
                return False
        
        print("✅ Diagnosis result validation passed")
        return True
        
    except Exception as e:
        print(f"❌ Error validating diagnosis result: {str(e)}")
        return False

def get_step6_qa_data():
    """Retrieve organized Q&A data from step 6 for use in step 7"""
    try:
        step6_data = get_step_data(6)
        if not step6_data:
            return {}
        
        ai_data = step6_data.get('ai_data', {})
        
        # Extract organized Q&A pairs
        qa_pairs = ai_data.get('organized_qa_pairs', [])
        question_responses = ai_data.get('question_responses', {})
        original_questions = ai_data.get('original_questions', [])
        
        return {
            'qa_pairs': qa_pairs,
            'total_questions_generated': ai_data.get('total_questions_generated', 0),
            'total_questions_answered': ai_data.get('total_questions_answered', 0),
            'completion_rate': ai_data.get('completion_rate', 0),
            'completed_at': ai_data.get('completed_at', ''),
            'raw_responses': question_responses,
            'raw_questions': original_questions,
            'session_metadata': ai_data.get('session_data', {})
        }
    except Exception as e:
        print(f"❌ Error retrieving step 6 Q&A data: {str(e)}")
        return {}

# Step 7 routes removed - now ending at step 6 with clinical summary

def generate_clinical_summary():
    """Generate a clinical summary using LLM based on steps 4, 5, and 6 data"""
    try:
        print("🏥 GENERATING CLINICAL SUMMARY...")
        
        # Get patient data from all steps
        patient_data = load_patient_data()
        print(f"📊 Loaded patient data: {list(patient_data.keys()) if patient_data else 'None'}")
        
        if not patient_data:
            print("❌ No patient data found for clinical summary")
            return {"error": "No patient data found"}
        
        # Extract relevant data from steps (note: demographics in step2, vitals in step3)
        step1_data = patient_data.get('step1', {})
        step2_data = patient_data.get('step2', {})  # Demographics
        step3_data = patient_data.get('step3', {})  # Vital signs
        step4_data = patient_data.get('step4', {})
        step5_data = patient_data.get('step5', {})
        step6_data = patient_data.get('step6', {})
        
        print(f"📋 Step data found: Step1={bool(step1_data)}, Step2={bool(step2_data)}, Step3={bool(step3_data)}, Step4={bool(step4_data)}, Step5={bool(step5_data)}, Step6={bool(step6_data)}")
        
        # Build comprehensive clinical context
        clinical_context = []
        
        # Patient Demographics (Step 2)
        step2_form = step2_data.get('form_data', {})
        if step2_form:
            demographics = []
            if 'full_name' in step2_form:
                demographics.append(f"Name: {step2_form['full_name']}")
            if 'calculated_age' in step2_form:
                demographics.append(f"Age: {step2_form['calculated_age']} years")
            if 'gender' in step2_form:
                demographics.append(f"Gender: {step2_form['gender']}")
            if 'occupation' in step2_form:
                demographics.append(f"Occupation: {step2_form['occupation']}")
            if 'marital_status' in step2_form:
                demographics.append(f"Marital Status: {step2_form['marital_status']}")
            
            # Medical history
            medical_history = []
            if step2_form.get('diabetes') == 'yes':
                medical_history.append("Diabetes")
            if step2_form.get('hypertension') == 'yes':
                medical_history.append("Hypertension")
            if step2_form.get('asthma') == 'yes':
                medical_history.append("Asthma")
            if step2_form.get('heart_disease') == 'yes':
                medical_history.append("Heart Disease")
            if medical_history:
                demographics.append(f"Medical History: {', '.join(medical_history)}")
                
            if demographics:
                clinical_context.append("PATIENT DEMOGRAPHICS:\n" + "\n".join(demographics))
        
        # Vital Signs & Measurements (Step 3)
        step3_form = step3_data.get('form_data', {})
        if step3_form:
            vitals = []
            if 'pulse_rate' in step3_form:
                vitals.append(f"Pulse Rate: {step3_form['pulse_rate']} bpm")
            if 'systolic_bp' in step3_form and 'diastolic_bp' in step3_form:
                vitals.append(f"Blood Pressure: {step3_form['systolic_bp']}/{step3_form['diastolic_bp']} mmHg")
            if 'respiratory_rate' in step3_form:
                vitals.append(f"Respiratory Rate: {step3_form['respiratory_rate']} breaths/min")
            if 'temperature' in step3_form:
                temp_unit = step3_form.get('temperature_unit', 'fahrenheit')
                vitals.append(f"Temperature: {step3_form['temperature']}°{temp_unit[0].upper()}")
            if 'oxygen_saturation' in step3_form:
                vitals.append(f"Oxygen Saturation: {step3_form['oxygen_saturation']}%")
            if 'blood_glucose' in step3_form:
                glucose_timing = step3_form.get('glucose_timing', 'random')
                vitals.append(f"Blood Glucose ({glucose_timing}): {step3_form['blood_glucose']} mg/dL")
            if 'bmi' in step3_form:
                vitals.append(f"BMI: {step3_form['bmi']} kg/m²")
            if 'lung_congestion' in step3_form:
                vitals.append(f"Lung Congestion: {step3_form['lung_congestion']}")
            
            if vitals:
                clinical_context.append("VITAL SIGNS & CLINICAL FINDINGS:\n" + "\n".join(vitals))
        
        # Symptoms & Complaints (Step 5)
        step5_form = step5_data.get('form_data', {})
        step5_ai = step5_data.get('ai_generated_data', {})
        if step5_form or step5_ai:
            symptoms = []
            
            # Chief complaint
            if 'complaint_text' in step5_form:
                symptoms.append(f"Chief Complaint: {step5_form['complaint_text']}")
            
            # Symptom insights from AI analysis
            if 'symptom_insights' in step5_ai:
                symptom_insights = step5_ai['symptom_insights']
                if isinstance(symptom_insights, dict) and 'medical_labels' in symptom_insights:
                    labels = symptom_insights['medical_labels']
                    condition_details = []
                    for label in labels:
                        if isinstance(label, dict):
                            name = label.get('label', '')
                            severity = label.get('severity', '')
                            description = label.get('description', '')
                            if name:
                                condition_details.append(f"- {name} ({severity}): {description}")
                    if condition_details:
                        symptoms.append("Symptom Analysis:\n" + "\n".join(condition_details))
            
            # Abnormal findings from AI analysis
            if 'abnormal_findings' in step5_ai:
                findings = step5_ai['abnormal_findings']
                if findings:
                    findings_list = []
                    for finding in findings:
                        if isinstance(finding, dict):
                            finding_text = finding.get('finding', '')
                            concern = finding.get('concern', '')
                            priority = finding.get('priority', '')
                            if finding_text:
                                findings_list.append(f"- {finding_text} (Concern: {concern}, Priority: {priority})")
                    if findings_list:
                        symptoms.append("Clinical Findings:\n" + "\n".join(findings_list))
            
            if symptoms:
                clinical_context.append("PRESENTING SYMPTOMS & CLINICAL FINDINGS:\n" + "\n".join(symptoms))
        
        # Detailed Assessment (Step 6)
        step6_ai = step6_data.get('ai_generated_data', {})
        if step6_ai and 'organized_qa_pairs' in step6_ai:
            responses = []
            qa_pairs = step6_ai['organized_qa_pairs']
            for qa_pair in qa_pairs:
                if isinstance(qa_pair, dict):
                    question = qa_pair.get('question_text', '')
                    answer = qa_pair.get('answer', '')
                    category = qa_pair.get('question_category', '')
                    if question and answer:
                        responses.append(f"Q ({category}): {question}")
                        responses.append(f"A: {answer}")
                        responses.append("")  # Empty line for readability
            
            if responses:
                clinical_context.append("DETAILED SYMPTOM ASSESSMENT:\n" + "\n".join(responses[:-1]))  # Remove last empty line
        
        if not clinical_context:
            return {"error": "Insufficient data for clinical summary"}
        
        full_context = "\n\n".join(clinical_context)
        
        # Create prompt for LLM to generate clinical summary
        prompt_template = load_prompt("clinical_summary")
        prompt = prompt_template.format(full_context=full_context)

        print("🤖 Sending clinical summary request to GPT-4o...")
        
        # Use GPT-4o for generating clinical summary
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": load_prompt("clinical_summary_system")
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.3,  # Lower temperature for more consistent medical documentation
            max_tokens=2000
        )
        
        clinical_summary = response.choices[0].message.content.strip()
        print(f"✅ Clinical summary generated: {len(clinical_summary)} characters")
        
        return {
            "success": True,
            "clinical_summary": clinical_summary,
            "data_sources": f"Steps 1, 4, 5, and 6 data compiled"
        }
        
    except Exception as e:
        print(f"❌ Error generating clinical summary: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": f"Failed to generate clinical summary: {str(e)}"}

@app.route('/generate_summary', methods=['POST'])
def generate_summary():
    """API endpoint to generate clinical summary"""
    try:
        summary_result = generate_clinical_summary()
        if "error" in summary_result:
            return jsonify({'success': False, 'error': summary_result['error']})
        
        return jsonify({
            'success': True,
            'summary': summary_result['clinical_summary'],
            'data_sources': summary_result['data_sources']
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': f'Summary generation failed: {str(e)}'})
# Report generation
@app.route('/report')
def report():
    """Generate comprehensive patient report - SHOULD NOT BE USED NOW as we replaced with popup"""
    try:
        all_data = get_all_patient_data()
        print(f"DEBUG: /report route accessed. Data found: {'Yes' if all_data else 'No'}")
        
        if not all_data or 'steps' not in all_data:
            print("DEBUG: No patient data or no steps found, redirecting to home")
            return redirect('/')
        
        print("DEBUG: Report route accessed but we now use popup instead")
        return redirect('/')
    except Exception as e:
        print(f"❌ Error in /report route: {str(e)}")
        return redirect('/')
        return redirect('/')

@app.route('/get_complete_patient_report', methods=['GET'])
def get_complete_patient_report():
    """Get complete patient data for report generation"""
    try:
        all_data = get_all_patient_data()
        if not all_data:
            return jsonify({'success': False, 'error': 'No patient data found'})
        
        # Organize data for easy report generation
        report_data = {
            'session_info': all_data.get('session_info', {}),
            'completion_status': all_data.get('completion_status', {}),
            'case_category': {},
            'patient_registration': {},
            'vital_signs': {},
            'medical_records': {},
            'complaints': {},
            'analysis': {},
            'diagnosis': {}
        }
        
        steps = all_data.get('steps', {})
        
        # Extract organized data for each section
        if 'step1' in steps:
            report_data['case_category'] = steps['step1']
        if 'step2' in steps:
            report_data['patient_registration'] = steps['step2']
        if 'step3' in steps:
            report_data['vital_signs'] = steps['step3']
        if 'step4' in steps:
            report_data['medical_records'] = steps['step4']
        if 'step5' in steps:
            report_data['complaints'] = steps['step5']
        if 'step6' in steps:
            report_data['analysis'] = steps['step6']
        # Step7 removed - clinical summary generated via LLM
        
        return jsonify({
            'success': True,
            'report_data': report_data,
            'total_steps_completed': len([k for k in steps.keys() if steps[k].get('step_completed', False)])
        })
        
    except Exception as e:
        print(f"❌ Error generating complete report: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to generate report: {str(e)}'})

@app.route('/get_patient_data', methods=['GET'])
def get_patient_data():
    """Get patient data from previous steps in clean format"""
    try:
        all_data = get_all_patient_data()
        if not all_data or 'steps' not in all_data:
            return jsonify({'success': False, 'error': 'No patient data found'})
        
        # Extract clean data from step-based structure
        cleaned_data = {
            'step1': {},
            'step2': {},
            'step3': {},
            'step4': {},
            'session_info': all_data.get('session_info', {}),
            'completion_status': all_data.get('completion_status', {})
        }
        
        # Extract data from each step
        for step_num in range(1, 5):
            step_key = f'step{step_num}'
            if step_key in all_data['steps']:
                step_data = all_data['steps'][step_key]
                cleaned_data[step_key] = {
                    'form_data': step_data.get('form_data', {}),
                    'ai_data': step_data.get('ai_generated_data', {}),
                    'files': step_data.get('files_uploaded', {}),
                    'timestamp': step_data.get('timestamp', ''),
                    'completed': step_data.get('step_completed', False)
                }
        
        # Legacy format for backward compatibility
        legacy_format = {
            'registration': cleaned_data['step2']['form_data'],
            'vitals': cleaned_data['step3']['form_data'],
            'step4_data': cleaned_data['step4']['form_data']
        }
        
        print(f"✅ Patient data retrieved successfully")
        print(f"📊 Steps with data: {[k for k, v in cleaned_data.items() if k.startswith('step') and v.get('form_data')]}")
        
        return jsonify({
            'success': True,
            'step_based_data': cleaned_data,
            'legacy_data': legacy_format,
            'registration': legacy_format['registration'],
            'vitals': legacy_format['vitals'],
            'step4_data': legacy_format['step4_data']
        })
        
    except Exception as e:
        print(f"❌ Error getting patient data: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to get patient data: {str(e)}'})

@app.route('/analyze_complaints', methods=['POST'])
def analyze_complaints():
    """Generate targeted follow-up questions based on step5 data using specific medical categories"""
    try:
        print("✅ ===== STARTING STEP 6 TARGETED QUESTIONS ANALYSIS =====")
        
        # Get patient data
        all_data = get_all_patient_data()
        if not all_data:
            print("❌ ERROR - No patient data found")
            return jsonify({'success': False, 'error': 'No patient data found'})
        
        # Extract step5 data only (as requested)
        step5_data = get_step_data(5)
        if not step5_data:
            print("❌ ERROR - No step5 data found")
            return jsonify({'success': False, 'error': 'Please complete step 5 first'})
        
        print(f"📊 Step 5 data available: {bool(step5_data)}")
        
        # Extract step5 components
        form_data = step5_data.get('form_data', {})
        ai_data = step5_data.get('ai_generated_data', {})
        
        # Prepare step5 context
        step5_context = {
            'complaint_text': form_data.get('complaint_text', ''),
            'primary_complaint': form_data.get('primary_complaint', ''),
            'symptom_duration': form_data.get('symptom_duration', ''),
            'pain_level': form_data.get('pain_level', ''),
            'additional_symptoms': form_data.get('additional_symptoms', ''),
            'abnormal_findings': ai_data.get('abnormal_findings', []),
            'symptom_insights': ai_data.get('symptom_insights', {}),
            'followup_answers': ai_data.get('followup_answers', {})
        }
        
        print(f"� Complaint text available: {bool(step5_context['complaint_text'])}")
        print(f"� Abnormal findings: {len(step5_context['abnormal_findings'])}")
        print(f"� AI insights available: {bool(step5_context['symptom_insights'])}")
        
        # Generate targeted questions based on step5 data
        questions = generate_targeted_step5_questions(step5_context)
        
        return jsonify({
            'success': True,
            'analysis': {
                'correlated_questions': questions,
                'source_data': 'step5_only',
                'total_questions': len(questions)
            }
        })
        
    except Exception as e:
        print(f"❌ Error in analyze_complaints: {str(e)}")
        return jsonify({'success': False, 'error': f'Analysis failed: {str(e)}'})

# Removed get_patient_friendly_term() function - now using LLM for medical term translation

def generate_targeted_step5_questions(step5_context):
    """Use LLM to generate 5th-grade level questions about medical conditions"""
    try:
        print("🎯 USING LLM TO GENERATE 5TH-GRADE LEVEL QUESTIONS...")
        
        # Extract data from step5
        complaint_text = step5_context.get('complaint_text', '')
        abnormal_findings = step5_context.get('abnormal_findings', [])
        symptom_insights = step5_context.get('symptom_insights', {})
        
        print(f"📊 STEP5 DATA INVENTORY:")
        print(f"   📝 Complaint text: '{complaint_text}'")
        print(f"   🚨 Abnormal findings: {len(abnormal_findings)}")
        print(f"   🧠 Symptom insights available: {bool(symptom_insights)}")
        
        # Extract medical labels
        medical_labels = []
        if symptom_insights and 'medical_labels' in symptom_insights:
            medical_labels = symptom_insights['medical_labels']
            print(f"🏷️ MEDICAL LABELS FOUND: {[label.get('label', '') for label in medical_labels if isinstance(label, dict)]}")
        
        # If no medical conditions found, use fallback
        if not medical_labels and not complaint_text.strip():
            print("⚠️ No specific medical conditions found, using fallback")
            return generate_fallback_targeted_questions()
        
        # Build comprehensive context for LLM
        context_parts = []
        
        if complaint_text:
            context_parts.append(f"PATIENT SAID: '{complaint_text}'")
        
        if medical_labels:
            labels_text = []
            for label in medical_labels:
                if isinstance(label, dict):
                    name = label.get('label', '')
                    severity = label.get('severity', 'mild')
                    description = label.get('description', '')
                    if name:
                        labels_text.append(f"- {name} ({severity}): {description}")
            if labels_text:
                context_parts.append("MEDICAL CONDITIONS IDENTIFIED:\n" + "\n".join(labels_text))
        
        if abnormal_findings:
            findings_text = []
            for finding in abnormal_findings[:3]:  # Limit to top 3
                if isinstance(finding, dict):
                    finding_desc = finding.get('finding', '') or finding.get('concern', '')
                    if finding_desc:
                        findings_text.append(f"- {finding_desc}")
            if findings_text:
                context_parts.append("ABNORMAL TEST RESULTS:\n" + "\n".join(findings_text))
        
        if not context_parts:
            print("⚠️ No meaningful step5 context found")
            return generate_fallback_targeted_questions()
        
        full_context = "\n\n".join(context_parts)
        
        # Calculate target number of questions based on medical conditions
        num_medical_conditions = len([label for label in medical_labels if isinstance(label, dict) and label.get('label')])
        if num_medical_conditions >= 4:
            target_questions = 12  # Maximum questions for 4+ conditions
        elif num_medical_conditions >= 2:
            target_questions = 10  # 10 questions for 2-3 conditions  
        else:
            target_questions = 8   # 8 questions for 1 condition or general symptoms
            
        print(f"🎯 TARGET: {target_questions} questions for {num_medical_conditions} medical conditions")
        
        # Create prompt for LLM - acting as medical expert who understands what patients actually experience
        prompt_template = load_prompt("dynamic_questions")
        prompt = prompt_template.format(
            full_context=full_context,
            target_questions=target_questions,
            num_medical_conditions=num_medical_conditions
        )

        print(f"🤖 Sending medically-expert prompt to GPT-4o...")
        print(f"📝 Context length: {len(full_context)} characters")
        
        # Use GPT-4o for generating simple, understandable questions
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": load_prompt("dynamic_questions_system")
                },
                {
                    "role": "user", 
                    "content": prompt
                }
            ],
            temperature=0.7,  # Slightly higher for more natural, friendly language
            max_tokens=3000
        )
        
        ai_response = response.choices[0].message.content.strip()
        print(f"🤖 GPT-4o response received: {len(ai_response)} characters")
        
        # Parse GPT-4o response
        try:
            # Extract JSON from response
            json_start = ai_response.find('[')
            json_end = ai_response.rfind(']') + 1
            
            if json_start >= 0 and json_end > json_start:
                json_content = ai_response[json_start:json_end]
                questions = json.loads(json_content)
                
                # Validate and clean questions
                valid_questions = []
                for q in questions:
                    if isinstance(q, dict) and 'question' in q and 'options' in q:
                        # Ensure question is practical and understandable
                        question_text = q['question']
                        if len(question_text.split()) <= 20:  # Reasonable length
                            valid_questions.append(q)
                
                print(f"✅ Generated {len(valid_questions)} MEDICALLY-EXPERT questions:")
                for i, q in enumerate(valid_questions, 1):
                    print(f"   {i}. {q['question']}")
                
                # Check if we have enough questions based on our target
                min_questions = max(6, target_questions - 2)  # At least 6, but allow 2 less than target
                if len(valid_questions) >= min_questions:
                    return valid_questions[:target_questions]  # Return exactly target number
                else:
                    print(f"⚠️ Only {len(valid_questions)} questions generated (target: {target_questions}), adding practical fallbacks...")
                    # Add practical fallback questions to reach target
                    practical_fallbacks = generate_simple_fallback_questions()
                    combined = valid_questions + practical_fallbacks[:(target_questions-len(valid_questions))]
                    return combined[:target_questions]
                
        except json.JSONDecodeError as e:
            print(f"❌ JSON parsing error: {str(e)}")
            print(f"Raw response sample: {ai_response[:300]}...")
        
        except Exception as e:
            print(f"❌ Error processing GPT-4o response: {str(e)}")
        
        # Fallback if LLM fails
        print(f"🔄 LLM failed, using {target_questions} practical fallback questions...")
        fallback_questions = generate_simple_fallback_questions()
        return fallback_questions[:target_questions]
        
    except Exception as e:
        print(f"❌ Error in LLM question generation: {str(e)}")
        import traceback
        traceback.print_exc()
        # Fallback with target number of questions
        fallback_questions = generate_simple_fallback_questions()
        return fallback_questions[:target_questions if 'target_questions' in locals() else 8]

def generate_simple_fallback_questions():
    """Generate practical fallback questions about common symptoms"""
    return [
        {
            "question": "When did you first notice you weren't feeling well?",
            "category": "onset",
            "type": "multiple_choice",
            "options": ["Less than an hour ago", "A few hours ago", "Yesterday", "A few days ago", "About a week ago", "More than a week ago"],
            "relevance": "Timing of symptom onset"
        },
        {
            "question": "Have you been feeling unusually tired or weak?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["No, normal energy", "A little more tired", "Pretty tired", "Very tired", "Extremely exhausted", "Energy comes and goes"],
            "relevance": "Fatigue levels and energy"
        },
        {
            "question": "Have you noticed any changes in your breathing?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["Breathing is normal", "Slightly short of breath", "Moderate breathing difficulty", "Hard to catch my breath", "Very hard to breathe", "Breathing problems come and go"],
            "relevance": "Respiratory symptoms"
        },
        {
            "question": "Have you been sweating more than usual or feeling hot?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["No changes", "Slightly more sweating", "Sweating quite a bit", "Sweating a lot", "Constant sweating", "Sweating comes in waves"],
            "relevance": "Temperature regulation and fever symptoms"
        },
        {
            "question": "How often do you feel these symptoms?",
            "category": "frequency",
            "type": "multiple_choice",
            "options": ["All the time", "Most of the day", "Several times a day", "Once a day", "Few times a week", "It's unpredictable"],
            "relevance": "Frequency and pattern of symptoms"
        },
        {
            "question": "What makes you feel worse?",
            "category": "aggravating",
            "type": "multiple_choice",
            "options": ["Physical activity", "Standing up", "Lying down", "Eating", "Heat or cold", "Nothing makes it worse"],
            "relevance": "Aggravating factors"
        },
        {
            "question": "What helps you feel better?",
            "category": "relieving",
            "type": "multiple_choice",
            "options": ["Resting", "Drinking fluids", "Fresh air", "Medication", "Nothing helps yet", "Haven't tried anything"],
            "relevance": "Relieving factors"
        },
        {
            "question": "How much are these symptoms affecting your daily activities?",
            "category": "severity",
            "type": "multiple_choice",
            "options": ["Not affecting me", "Slightly bothersome", "Somewhat limiting", "Very limiting", "Can't do normal activities", "Affects some things but not others"],
            "relevance": "Functional impact and severity"
        },
        {
            "question": "Have you been more thirsty than usual?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["No change", "Slightly more thirsty", "Pretty thirsty", "Very thirsty", "Extremely thirsty", "Thirst comes and goes"],
            "relevance": "Metabolic symptoms like dehydration"
        },
        {
            "question": "Have you noticed your heart beating fast or irregularly?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["Heart feels normal", "Sometimes beats fast", "Often beats fast", "Heart races frequently", "Heart feels like it's pounding", "Heart rhythm feels irregular"],
            "relevance": "Cardiovascular symptoms"
        }
    ]

def generate_fallback_targeted_questions():
    """Generate 8 fallback questions organized by the required categories"""
    fallback_questions = [
        {
            "question": "When did these symptoms first begin?",
            "category": "onset",
            "type": "multiple_choice",
            "options": ["Less than 1 hour ago", "2-6 hours ago", "12-24 hours ago", "2-3 days ago", "1 week ago", "More than 1 week ago"],
            "relevance": "Essential for understanding symptom timeline"
        },
        {
            "question": "How would you describe the pattern of your symptoms?",
            "category": "duration", 
            "type": "multiple_choice",
            "options": ["Constant throughout the day", "Comes and goes in episodes", "Getting progressively worse", "Getting gradually better", "Stays about the same", "Varies unpredictably"],
            "relevance": "Important for understanding symptom progression"
        },
        {
            "question": "How severe are your symptoms on average?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["Mild (1-3/10 - minimal interference)", "Moderate (4-6/10 - some interference)", "Severe (7-8/10 - major interference)", "Very severe (9-10/10 - can't function)", "Varies throughout the day", "Hard to rate"],
            "relevance": "Critical for assessing symptom intensity"
        },
        {
            "question": "How would you describe the quality of your symptoms?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["Sharp/stabbing", "Dull/aching", "Throbbing", "Burning", "Cramping", "Other quality"],
            "relevance": "Important for characterizing symptom quality"
        },
        {
            "question": "Where do you feel your symptoms most strongly?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["One specific location", "Multiple separate areas", "Moves around/radiates", "Whole body/generalized", "Hard to pinpoint exactly", "Not applicable"],
            "relevance": "Important for localization of symptoms"
        },
        {
            "question": "What activities or situations make your symptoms worse?",
            "category": "aggravating",
            "type": "multiple_choice",
            "options": ["Physical activity/movement", "Stress or anxiety", "Eating or drinking", "Weather changes", "Lying down", "Standing/walking", "Nothing makes it worse", "Multiple triggers"],
            "relevance": "Identifies triggers that worsen symptoms"
        },
        {
            "question": "What helps relieve or improve your symptoms?",
            "category": "relieving",
            "type": "multiple_choice",
            "options": ["Rest", "Over-the-counter medication", "Heat application", "Cold application", "Position changes", "Nothing has helped", "Haven't tried anything", "Multiple things help"],
            "relevance": "Identifies effective relief methods"
        },
        {
            "question": "How much do your symptoms interfere with your daily activities?",
            "category": "characteristics",
            "type": "multiple_choice",
            "options": ["Not at all", "Slightly", "Moderately", "Quite a bit", "Extremely", "Varies by day"],
            "relevance": "Functional impact assessment"
        }
    ]
    
    print(f"🔄 Generated {len(fallback_questions)} fallback targeted questions")
    return fallback_questions

def extract_specific_symptoms(complaint_text):
    """Extract specific symptoms mentioned in the complaint text"""
    if not complaint_text:
        return []
    
    text = complaint_text.lower()
    symptoms = []
    
    # Common symptoms to look for
    symptom_patterns = {
        'headache': ['headache', 'head pain', 'head hurt'],
        'fever': ['fever', 'temperature', 'hot', 'chills'],
        'nausea': ['nausea', 'nauseous', 'sick to stomach'],
        'vomiting': ['vomiting', 'throwing up', 'vomit'],
        'dizziness': ['dizzy', 'dizziness', 'lightheaded'],
        'fatigue': ['tired', 'fatigue', 'exhausted', 'weak'],
        'chest pain': ['chest pain', 'chest hurt', 'chest pressure'],
        'shortness of breath': ['short of breath', 'breathing difficulty', 'cant breathe'],
        'stomach pain': ['stomach pain', 'stomach ache', 'abdominal pain'],
        'back pain': ['back pain', 'back hurt', 'back ache'],
        'cough': ['cough', 'coughing'],
        'sore throat': ['sore throat', 'throat pain', 'throat hurt']
    }
    
    for symptom, patterns in symptom_patterns.items():
        for pattern in patterns:
            if pattern in text:
                symptoms.append(symptom)
                break
    
    # Remove duplicates and return top 3 most relevant
    return list(dict.fromkeys(symptoms))[:3]

@app.route('/generate_followup_questions', methods=['POST'])
def generate_followup_questions():
    """Generate AI follow-up questions based on out-of-range vitals from step3"""
    try:
        print("✅ ===== STARTING FOLLOW-UP QUESTIONS GENERATION =====")
        
        # Get all patient data using new structure
        all_data = get_all_patient_data()
        if not all_data or 'steps' not in all_data:
            print("❌ ERROR - No patient data found")
            return jsonify({'success': False, 'error': 'No patient data found'})
        
        print(f"📊 Available steps: {list(all_data['steps'].keys())}")
        
        # Get vitals from step3
        vitals = {}
        patient_identity = {}
        
        if 'step3' in all_data['steps']:
            step3_data = all_data['steps']['step3']
            vitals = step3_data.get('form_data', {})
            print(f"📋 Vitals from step3: {len(vitals)} fields")
        
        # Get patient identity from step1 or step2
        if 'step2' in all_data['steps']:
            step2_data = all_data['steps']['step2']
            patient_identity = step2_data.get('form_data', {})
            print(f"👤 Patient identity from step2: {len(patient_identity)} fields")
        elif 'step1' in all_data['steps']:
            step1_data = all_data['steps']['step1']
            patient_identity = step1_data.get('form_data', {})
            print(f"👤 Patient identity from step1: {len(patient_identity)} fields")
        
        if not vitals:
            print("❌ ERROR - No vitals data found")
            return jsonify({'success': False, 'error': 'No vitals data found. Please complete Step 3 first.'})
        
        # Log vitals inventory
        print("📊 ===== VITAL SIGNS INVENTORY =====")
        vital_keys = ['temperature', 'temperature_unit', 'pulse_rate', 'systolic_bp', 'diastolic_bp', 
                     'respiratory_rate', 'oxygen_saturation', 'blood_glucose', 'bmi', 
                     'weight', 'height', 'ecg_available', 'ecg_findings', 
                     'lung_congestion', 'water_in_lungs']
        
        for key in vital_keys:
            value = vitals.get(key)
            print(f"   {key}: '{value}' (type: {type(value)})")
        
        print("===== END INVENTORY =====")
        
        # Get temperature unit and adjust temperature ranges accordingly
        temperature_unit = vitals.get('temperature_unit', 'celsius')
        print(f"🌡️ Temperature unit detected: {temperature_unit}")
        
        # Define temperature ranges based on unit
        if temperature_unit == 'fahrenheit':
            temp_range = {'min': 97.0, 'max': 99.0, 'unit': '°F', 'name': 'Body Temperature'}
            temp_critical_low = 95.0
            temp_critical_high = 102.2
        else:  # celsius (default)
            temp_range = {'min': 36.1, 'max': 37.2, 'unit': '°C', 'name': 'Body Temperature'}
            temp_critical_low = 35.0
            temp_critical_high = 39.0
        
        print(f"🌡️ Using temperature range: {temp_range['min']}-{temp_range['max']} {temp_range['unit']}")
        
        # Define comprehensive normal ranges
        normal_ranges = {
            'temperature': temp_range,
            'pulse_rate': {'min': 60, 'max': 100, 'unit': 'bpm', 'name': 'Pulse Rate'},
            'systolic_bp': {'min': 90, 'max': 120, 'unit': 'mmHg', 'name': 'Systolic Blood Pressure'},
            'diastolic_bp': {'min': 60, 'max': 80, 'unit': 'mmHg', 'name': 'Diastolic Blood Pressure'},
            'respiratory_rate': {'min': 12, 'max': 20, 'unit': 'breaths/min', 'name': 'Respiratory Rate'},
            'oxygen_saturation': {'min': 95, 'max': 100, 'unit': '%', 'name': 'Oxygen Saturation'},
            'blood_glucose': {'min': 70, 'max': 140, 'unit': 'mg/dL', 'name': 'Blood Glucose'},
            'bmi': {'min': 18.5, 'max': 24.9, 'unit': 'kg/m²', 'name': 'Body Mass Index'},
            'weight': {'min': 40, 'max': 200, 'unit': 'kg', 'name': 'Weight'},
            'height': {'min': 140, 'max': 220, 'unit': 'cm', 'name': 'Height'}
        }
        
        # Analyze vitals for abnormalities
        abnormal_findings = []
        critical_findings = []
        
        print("🔍 Starting comprehensive vitals analysis...")
        
        for vital_name, ranges in normal_ranges.items():
            vital_value = vitals.get(vital_name)
            print(f"   Checking {vital_name}: '{vital_value}' (range: {ranges['min']}-{ranges['max']} {ranges['unit']})")
            
            if vital_value is not None and str(vital_value).strip():
                try:
                    value = float(vital_value)
                    
                    # Check if value is outside normal range
                    if value < ranges['min'] or value > ranges['max']:
                        print(f"   ⚠️ ABNORMAL - {vital_name}: {value} {ranges['unit']} outside range {ranges['min']}-{ranges['max']}")
                        
                        # Determine severity level
                        severity = 'abnormal'
                        
                        # Define critical thresholds
                        if vital_name == 'temperature' and (value < temp_critical_low or value > temp_critical_high):
                            severity = 'critical'
                        elif vital_name == 'pulse_rate' and (value < 50 or value > 120):
                            severity = 'critical'
                        elif vital_name == 'systolic_bp' and (value < 80 or value > 160):
                            severity = 'critical'
                        elif vital_name == 'diastolic_bp' and (value < 50 or value > 100):
                            severity = 'critical'
                        elif vital_name == 'oxygen_saturation' and value < 90:
                            severity = 'critical'
                        elif vital_name == 'blood_glucose' and (value < 60 or value > 200):
                            severity = 'critical'
                        elif vital_name == 'respiratory_rate' and (value < 8 or value > 30):
                            severity = 'critical'
                        
                        finding = {
                            'parameter': vital_name,
                            'parameter_name': ranges['name'],
                            'value': value,
                            'normal_range': f"{ranges['min']}-{ranges['max']}",
                            'unit': ranges['unit'],
                            'severity': severity,
                            'deviation': 'high' if value > ranges['max'] else 'low'
                        }
                        
                        if severity == 'critical':
                            critical_findings.append(finding)
                            print(f"   🚨 CRITICAL finding added: {finding}")
                        else:
                            abnormal_findings.append(finding)
                            print(f"   ⚠️ ABNORMAL finding added: {finding}")
                    else:
                        print(f"   ✅ NORMAL - {vital_name}: {value} {ranges['unit']}")
                except (ValueError, TypeError) as e:
                    print(f"   ❌ Could not convert {vital_name} value '{vital_value}' to float: {e}")
                    continue
            else:
                print(f"   ⚪ No value provided for {vital_name}")
        
        print(f"📊 Analysis complete - {len(abnormal_findings)} abnormal, {len(critical_findings)} critical findings")
        
        # Check for additional concerning clinical information
        concerning_findings = []
        
        # ECG findings
        if vitals.get('ecg_available') == 'yes':
            ecg_findings = vitals.get('ecg_findings', '').strip()
            if ecg_findings and ecg_findings.lower() not in ['normal', 'none', 'n/a', 'na']:
                concerning_findings.append({
                    'category': 'ECG',
                    'finding': ecg_findings,
                    'severity': 'concerning'
                })
                print(f"💓 ECG concern found: {ecg_findings}")
        
        # Respiratory findings
        lung_congestion = vitals.get('lung_congestion', '').strip()
        water_in_lungs = vitals.get('water_in_lungs', '').strip()
        
        if lung_congestion and lung_congestion.lower() not in ['no', 'none', 'normal']:
            concerning_findings.append({
                'category': 'Respiratory',
                'finding': f"Lung congestion: {lung_congestion}",
                'severity': 'concerning'
            })
            print(f"🫁 Lung congestion concern: {lung_congestion}")
            
        if water_in_lungs and water_in_lungs.lower() not in ['no', 'none', 'normal']:
            concerning_findings.append({
                'category': 'Respiratory', 
                'finding': f"Fluid in lungs: {water_in_lungs}",
                'severity': 'concerning'
            })
            print(f"🫁 Lung fluid concern: {water_in_lungs}")
        
        # Combine all findings
        all_findings = critical_findings + abnormal_findings
        total_concerns = len(all_findings) + len(concerning_findings)
        
        print(f"📊 Total medical concerns to address: {total_concerns}")
        
        # If NO abnormal findings at all, return no questions
        if total_concerns == 0:
            print("✅ No abnormal findings detected - patient appears healthy")
            return jsonify({
                'success': True,
                'questions': [],
                'message': 'All vital signs appear within normal ranges. No follow-up questions needed.',
                'findings_type': 'normal'
            })
        
        # Generate AI follow-up questions for abnormal findings
        patient_name = patient_identity.get('full_name', 'Patient')
        age = patient_identity.get('calculated_age', patient_identity.get('age', 'Unknown'))
        gender = patient_identity.get('gender', 'Unknown')
        
        print(f"👤 Patient info - Name: {patient_name}, Age: {age}, Gender: {gender}")
        
        # Build findings summary for AI
        findings_summary = []
        
        # Add vital sign abnormalities
        for finding in all_findings:
            deviation_text = "ELEVATED" if finding['deviation'] == 'high' else "LOW"
            findings_summary.append(
                f"{finding['parameter_name']}: {finding['value']} {finding['unit']} "
                f"({deviation_text} - Normal: {finding['normal_range']} {finding['unit']}) "
                f"[{finding['severity'].upper()}]"
            )
        
        # Add clinical concerns
        for concern in concerning_findings:
            findings_summary.append(f"{concern['category']}: {concern['finding']} [{concern['severity'].upper()}]")
        
        if not findings_summary:
            print("ℹ️ No findings to generate questions for")
            return jsonify({
                'success': True,
                'questions': [],
                'message': 'No abnormal findings detected.',
                'findings_type': 'normal'
            })
        
        findings_text = "\n".join([f"• {finding}" for finding in findings_summary])
        print(f"📝 Findings for AI analysis:\n{findings_text}")
        
        # Create AI prompt
        prompt_template = load_prompt("abnormal_vitals_followup")
        prompt = prompt_template.format(
            age=age,
            gender=gender,
            patient_name=patient_name,
            findings_text=findings_text
        )
        
        print(f"🤖 Sending prompt to AI (length: {len(prompt)} chars)")
        
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system", 
                        "content": load_prompt("followup_questions_system")
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1200,
                temperature=0.2
            )
            
            questions_text = response.choices[0].message.content.strip()
            print(f"🤖 Raw AI response: {questions_text[:300]}...")
            
            # Clean JSON response
            if questions_text.startswith('```json'):
                questions_text = questions_text[7:]
            if questions_text.endswith('```'):
                questions_text = questions_text[:-3]
            questions_text = questions_text.strip()
            
            # Parse AI-generated questions
            try:
                ai_questions = json.loads(questions_text)
                print(f"✅ Successfully parsed {len(ai_questions)} AI questions")
                
                # Validate and limit questions
                valid_questions = []
                for q in ai_questions:
                    if isinstance(q, dict) and 'question' in q and 'abnormal_finding' in q:
                        valid_questions.append({
                            'abnormal_finding': q.get('abnormal_finding', 'Unknown finding'),
                            'question': q.get('question', ''),
                            'priority': q.get('priority', 'medium'),
                            'medical_concern': q.get('medical_concern', 'general')
                        })
                    if len(valid_questions) >= 8:
                        break
                
                print(f"✅ Final {len(valid_questions)} valid questions generated")
                
                return jsonify({
                    'success': True,
                    'questions': valid_questions,
                    'findings_count': len(all_findings),
                    'critical_count': len(critical_findings),
                    'concerning_count': len(concerning_findings),
                    'findings_type': 'critical' if critical_findings else 'abnormal'
                })
                
            except json.JSONDecodeError as e:
                print(f"❌ JSON parse error: {e}")
                
                # Generate fallback questions
                fallback_questions = []
                
                symptom_map = {
                    'temperature_high': 'fever, chills, sweating, or fatigue',
                    'temperature_low': 'chills, shivering, or feeling cold',
                    'pulse_rate_high': 'palpitations, chest racing, or anxiety',
                    'pulse_rate_low': 'dizziness, fatigue, or fainting',
                    'systolic_bp_high': 'headaches, chest pain, or vision changes',
                    'systolic_bp_low': 'dizziness, lightheadedness, or fainting',
                    'oxygen_saturation_low': 'shortness of breath, chest tightness, or difficulty breathing',
                    'blood_glucose_high': 'increased thirst, frequent urination, or blurred vision',
                    'blood_glucose_low': 'shakiness, sweating, confusion, or weakness'
                }
                
                for finding in all_findings[:4]:
                    param_name = finding['parameter_name']
                    value = finding['value']
                    unit = finding['unit']
                    normal_range = finding['normal_range']
                    deviation = "elevated" if finding['deviation'] == 'high' else "low"
                    severity = finding['severity']
                    
                    symptom_key = f"{finding['parameter']}_{deviation}"
                    symptoms = symptom_map.get(symptom_key, "any unusual symptoms")
                    
                    fallback_questions.append({
                        "abnormal_finding": f"{param_name}: {value} {unit} (Normal: {normal_range} {unit})",
                        "question": f"Your {param_name.lower()} is {value} {unit}, which is {deviation} compared to the normal range of {normal_range} {unit}. Are you experiencing any related symptoms like {symptoms}?",
                        "priority": "critical" if severity == 'critical' else "high",
                        "medical_concern": f"{deviation}_{finding['parameter']}"
                    })
                
                return jsonify({
                    'success': True,
                    'questions': fallback_questions[:8],
                    'findings_count': len(all_findings),
                    'critical_count': len(critical_findings),
                    'concerning_count': len(concerning_findings),
                    'findings_type': 'critical' if critical_findings else 'abnormal',
                    'note': 'Using fallback questions due to AI parsing error'
                })
                
        except Exception as e:
            print(f"❌ Error calling OpenAI API: {e}")
            return jsonify({
                'success': False, 
                'error': f'Failed to generate AI questions: {str(e)}',
                'findings_count': len(all_findings)
            })
            
    except Exception as e:
        print(f"❌ Error generating follow-up questions: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Failed to generate questions: {str(e)}'})

@app.route('/analyze_medical_document', methods=['POST'])
def analyze_medical_document():
    """Analyze uploaded medical documents using AI"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'})
        
        file = request.files['file']
        doc_type = request.form.get('type', 'unknown')
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'})
        
        # In a real implementation, you would:
        # 1. Save the file securely
        # 2. Use OCR to extract text from images/PDFs
        # 3. Use AI to analyze the extracted text
        # 4. Return structured information
        
        # For now, return a mock analysis
        mock_analysis = {
            'lab': 'Blood glucose: 140 mg/dL (slightly elevated)\nHemoglobin: 12.5 g/dL (normal)\nChol: 220 mg/dL (borderline high)',
            'image': 'X-ray shows clear lung fields with no signs of infection or abnormalities. Heart size appears normal.',
            'signal': 'ECG shows normal sinus rhythm with heart rate of 72 bpm. No signs of arrhythmia or ischemia detected.'
        }
        
        analysis = mock_analysis.get(doc_type, 'Document uploaded successfully. Analysis pending.')
        
        return jsonify({
            'success': True,
            'extracted_info': analysis,
            'filename': file.filename
        })
        
    except Exception as e:
        print(f"Error analyzing medical document: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to analyze document: {str(e)}'})

# Step 4 has been re-implemented

@app.route('/step4_old')
def step4_old():
    """Old step 4 redirect - redirect to new step4"""
    return redirect('/step4')

# Enhanced Step 3 Routes
@app.route('/get_patient_summary', methods=['GET'])
def get_patient_summary():
    """Get patient summary from previous steps"""
    if not validate_session_step(3):
        return jsonify({'success': False, 'error': 'Please complete previous steps'})
    
    patient_data = session['patient_data']
    registration = patient_data.get('registration', {})
    
    # Extract patient name from multiple possible fields
    patient_name = (registration.get('full_name') or 
                   registration.get('name') or 
                   registration.get('patient_name') or 
                   'Not provided')
    
    # Extract contact information
    phone = registration.get('phone') or registration.get('phone_number') or ''
    email = registration.get('email') or ''
    patient_contact = f"{phone} {email}".strip() or 'Not provided'
    
    # Check if emergency contact already set
    emergency_contact = registration.get('emergency_contact') or 'Not set'
    
    return jsonify({
        'success': True,
        'patient_name': patient_name,
        'patient_contact': patient_contact,
        'emergency_contact': emergency_contact
    })

def create_fallback_analysis(content, category):
    """Create a fallback analysis structure when JSON parsing fails"""
    print(f"DEBUG: Creating fallback analysis for category: {category}")
    
    # Extract useful information from the text response
    lines = content.split('\n')
    summary_text = []
    findings = []
    recommendations = []
    
    current_section = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # Detect section headers
        if any(keyword in line.lower() for keyword in ['summary', 'interpretation', 'conclusion']):
            current_section = 'summary'
        elif any(keyword in line.lower() for keyword in ['finding', 'observation', 'result']):
            current_section = 'findings'
        elif any(keyword in line.lower() for keyword in ['recommend', 'suggest', 'follow']):
            current_section = 'recommendations'
        elif line.startswith('•') or line.startswith('-') or line.startswith('*'):
            # Bullet point - add to current section
            clean_line = line.lstrip('•-* ').strip()
            if current_section == 'findings':
                findings.append(clean_line)
            elif current_section == 'recommendations':
                recommendations.append(clean_line)
            else:
                summary_text.append(clean_line)
        elif line and not line.startswith('{') and not line.startswith('}'):
            # Regular text line
            if current_section == 'summary':
                summary_text.append(line)
            elif current_section == 'findings':
                findings.append(line)
            elif current_section == 'recommendations':
                recommendations.append(line)
            else:
                summary_text.append(line)
    
    # Create structured response
    fallback_analysis = {
        "summary": ' '.join(summary_text) if summary_text else "AI analysis completed successfully.",
        "key_findings": findings if findings else ["Analysis results available in summary"],
        "abnormal_values": [],  # Will be populated if specific patterns found
        "recommendations": recommendations if recommendations else ["Consult with healthcare provider for detailed interpretation"],
        "follow_up": "Please review with your healthcare provider for clinical correlation",
        "confidence": "Medium"
    }
    
    # Look for abnormal values or concerning findings
    abnormal_patterns = ['abnormal', 'elevated', 'decreased', 'high', 'low', 'concerning', 'pathologic']
    for line in lines:
        if any(pattern in line.lower() for pattern in abnormal_patterns):
            fallback_analysis["abnormal_values"].append(line.strip())
    
    print(f"DEBUG: Fallback analysis created: {fallback_analysis}")
    return fallback_analysis

@app.route('/analyze_medical_report', methods=['POST'])
def analyze_medical_report():
    """Analyze uploaded medical reports using AI"""
    # Remove session validation for medical report analysis
    print("DEBUG: Medical report analysis requested")
    
    try:
        # Handle both FormData and JSON formats
        if request.content_type and 'multipart/form-data' in request.content_type:
            print("DEBUG: Processing FormData upload")
            # Handle FormData upload (from our new JavaScript)
            uploaded_file = request.files.get('file')
            report_type = request.form.get('report_type', '')
            
            print(f"DEBUG: Uploaded file: {uploaded_file}")
            print(f"DEBUG: Report type: {report_type}")
            
            if not uploaded_file:
                print("ERROR: No file uploaded")
                return jsonify({'success': False, 'error': 'No file uploaded'})
            
            # Read and encode file data
            file_content = uploaded_file.read()
            file_data = base64.b64encode(file_content).decode('utf-8')
            file_name = uploaded_file.filename
            file_type = uploaded_file.content_type or 'image/jpeg'
            
            print(f"DEBUG: File name: {file_name}")
            print(f"DEBUG: File type: {file_type}")
            print(f"DEBUG: File data length: {len(file_data)}")
            
            # Determine category from report_type with comprehensive mapping
            if report_type in ['lab', 'laboratory']:
                category = 'laboratory'
            elif report_type in ['image', 'medical_image', 'medical_images']:
                category = 'medical_image'
            elif report_type in ['pathology', 'pathology_report']:
                category = 'pathology'
            elif report_type in ['signaling', 'signal', 'signaling_report', 'ecg', 'eeg']:
                category = 'signal'
            else:
                # Fallback mapping
                category = report_type
                print(f"WARNING: Unknown report_type '{report_type}', using as category")
                
            print(f"DEBUG: Mapped category: {category} from report_type: {report_type}")
                
        else:
            print("DEBUG: Processing JSON upload")
            # Handle JSON format (existing functionality)
            data = request.get_json()
            file_data = data.get('file_data')
            file_name = data.get('file_name')
            file_type = data.get('file_type')
            category = data.get('category')  # laboratory, medical_image, signal, pathology
            report_type = data.get('report_type', '')
        
        if not file_data:
            return jsonify({'success': False, 'error': 'No file data provided'})
        
        # Create specialized prompt based on category
        if category in ['laboratory', 'lab']:
            prompt_template = load_prompt("educational_lab_analysis")
            prompt = prompt_template.format(file_name=file_name)
        elif category in ['medical_image', 'image']:
            prompt_template = load_prompt("educational_medical_image_analysis")
            prompt = prompt_template.format(file_name=file_name, report_type=report_type)
        elif category == 'pathology':
            prompt_template = load_prompt("educational_pathology_analysis")
            prompt = prompt_template.format(file_name=file_name)
        elif category in ['signal', 'signaling']:
            prompt_template = load_prompt("educational_signal_analysis")
            prompt = prompt_template.format(file_name=file_name, report_type=report_type)
        else:
            return jsonify({'success': False, 'error': 'Invalid report category'})
        
        # Call OpenAI API for analysis
        response = openai_client.chat.completions.create(
            model="gpt-4o",  # Best model for image analysis
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{file_type};base64,{file_data}",
                                "detail": "high"  # Use high detail for better analysis
                            }
                        }
                    ]
                }
            ],
            max_tokens=2000,  # Increased for more detailed analysis
            temperature=0.1   # Lower temperature for more consistent medical analysis
        )
        
        content = response.choices[0].message.content.strip()
        print(f"DEBUG: OpenAI Response for {file_name} (category: {category}, report_type: {report_type})")
        print(f"DEBUG: Raw response length: {len(content)} characters")
        print(f"DEBUG: Raw response preview: {content[:200]}...")
        
        # Check if content is empty
        if not content:
            print("ERROR: Empty response from OpenAI API")
            return jsonify({'success': False, 'error': 'Empty response from AI analysis'})
        
        # More robust JSON parsing
        analysis = None
        
        # First, try to parse as direct JSON
        try:
            analysis = json.loads(content)
            print("DEBUG: Successfully parsed direct JSON")
        except json.JSONDecodeError:
            print("DEBUG: Direct JSON parsing failed, trying markdown cleanup")
            
            # Remove markdown code blocks
            cleaned_content = content
            if content.startswith('```json'):
                cleaned_content = content[7:]
                if cleaned_content.endswith('```'):
                    cleaned_content = cleaned_content[:-3]
            elif content.startswith('```'):
                cleaned_content = content[3:]
                if cleaned_content.endswith('```'):
                    cleaned_content = cleaned_content[:-3]
            
            cleaned_content = cleaned_content.strip()
            
            try:
                analysis = json.loads(cleaned_content)
                print("DEBUG: Successfully parsed cleaned JSON")
            except json.JSONDecodeError as e:
                print(f"ERROR: JSON parsing failed after cleanup: {str(e)}")
                print(f"DEBUG: Cleaned content: {cleaned_content}")
                
                # Try to extract JSON from mixed content using regex
                import re
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', cleaned_content, re.DOTALL)
                if json_match:
                    try:
                        analysis = json.loads(json_match.group())
                        print("DEBUG: Successfully extracted JSON using regex")
                    except json.JSONDecodeError:
                        print("ERROR: Regex-extracted JSON is still invalid")
                        # Create fallback analysis from the text response
                        analysis = create_fallback_analysis(content, category)
                else:
                    print("ERROR: No JSON pattern found in response")
                    # Create fallback analysis from the text response
                    analysis = create_fallback_analysis(content, category)
        
        if not analysis:
            return jsonify({'success': False, 'error': 'Failed to parse AI response'})
        
        print(f"DEBUG: Final analysis object: {analysis}")
        
        # Ensure patient_data exists in session
        if 'patient_data' not in session:
            session['patient_data'] = {}
            print("DEBUG: Initialized empty patient_data in session")
        
        # Store analysis in session
        if 'medical_reports_analysis' not in session['patient_data']:
            session['patient_data']['medical_reports_analysis'] = []
            print("DEBUG: Initialized medical_reports_analysis list")
        
        session['patient_data']['medical_reports_analysis'].append({
            'file_name': file_name,
            'category': category,
            'report_type': report_type,
            'analysis': analysis,
            'analyzed_at': datetime.now().isoformat()
        })
        session.modified = True
        
        return jsonify({
            'success': True,
            'insights': analysis
        })
        
    except Exception as e:
        print(f"ERROR: Exception in analyze_medical_report: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': f'Analysis failed: {str(e)}'})

# API endpoints for patient data management

# API endpoints for patient data management
@app.route('/api/get_patient_data', methods=['GET'])
def api_get_patient_data():
    """API endpoint to get patient data from file storage"""
    try:
        patient_data = load_patient_data()
        if not patient_data:
            return jsonify({'success': False, 'error': 'No patient data found'})
        
        # Extract relevant data for frontend
        response_data = {
            'success': True,
            'patient_name': '',
            'phone': '',
            'email': '',
            'hospital_selection': ''
        }
        
        # Get patient name from registration data
        if 'registration' in patient_data:
            reg_data = patient_data['registration']
            first_name = reg_data.get('first_name', '')
            last_name = reg_data.get('last_name', '')
            response_data['patient_name'] = f"{first_name} {last_name}".strip()
            response_data['phone'] = reg_data.get('phone', '')
            response_data['email'] = reg_data.get('email', '')
            response_data['hospital_selection'] = reg_data.get('hospital_selection', '')
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error in api_get_patient_data: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to load patient data: {str(e)}'})

@app.route('/api/save_patient_data', methods=['POST'])
def api_save_patient_data():
    """API endpoint to save patient data to file storage"""
    try:
        request_data = request.get_json()
        if not request_data:
            return jsonify({'success': False, 'error': 'No data provided'})
        
        step = request_data.get('step')
        data = request_data.get('data')
        
        if not step or not data:
            return jsonify({'success': False, 'error': 'Missing step or data'})
        
        # Load existing patient data
        patient_data = load_patient_data()
        if not patient_data:
            patient_data = {'created_at': datetime.now().isoformat()}
        
        # Step 4 functionality has been removed
        if step == 'step4':
            return jsonify({'success': False, 'error': 'Step 4 has been removed from this application'})
        
        # Save to file
        if save_patient_data(patient_data):
            print(f"Patient data saved successfully for {step}")
            
            # Update data timestamp (only if not step4)
            if step != 'step4':
                update_data_timestamp(int(step.replace('step', '')))
            
            # Update session minimally (skip for step4)
            if step != 'step4' and 'patient_data' not in session:
                session['patient_data'] = {}
                session['patient_data']['step_completed'] = int(step.replace('step', ''))
                session.modified = True
            
            return jsonify({'success': True, 'message': f'Data saved successfully for {step}'})
        else:
            return jsonify({'success': False, 'error': 'Failed to save data to file'})
            
    except Exception as e:
        print(f"Error in api_save_patient_data: {str(e)}")
        return jsonify({'success': False, 'error': f'Failed to save data: {str(e)}'})

# Main application code continues here
if __name__ == '__main__':
    api_key = os.getenv('OPENAI_API_KEY')
    print(f"OpenAI API Key loaded: {'Yes' if api_key else 'No'}")
    if api_key:
        print(f"API Key starts with: {api_key[:10]}...")
    app.run(host='0.0.0.0', port=5001, debug=True)

