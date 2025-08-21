## Dynamic Question Generation Summary

### 📊 **Question Scaling Logic**

The system now dynamically generates questions based on the number of medical conditions found in Step 5:

| Medical Conditions | Target Questions | Strategy |
|-------------------|------------------|----------|
| **4+ conditions** | **12 questions** | Maximum detail - 2-3 questions per condition |
| **2-3 conditions** | **10 questions** | Moderate detail - 3-4 questions per condition |  
| **1 condition** | **8 questions** | Focused detail - 6-8 questions on single condition |

### 🎯 **Question Distribution**

For each medical condition, the system asks about:
- **Onset**: When did symptoms start?
- **Characteristics**: How does it feel/appear? 
- **Frequency**: How often does it happen?
- **Severity**: How bad is it?
- **Relieving factors**: What makes it better?
- **Aggravating factors**: What makes it worse?

### 📋 **Example Scenarios**

**Patient with 4 conditions** (Hyperthermia, Hypoxemia, Hyperglycemia, Obesity):
- Gets **12 questions** covering all conditions
- Example: "When did your fever start?", "What makes your breathing worse?", "How often do you feel extremely thirsty?", etc.

**Patient with 2 conditions** (Fever, Nausea):
- Gets **10 questions** with detailed focus on both conditions

**Patient with 1 condition** (Headache):
- Gets **8 questions** with comprehensive coverage of that single condition

### ✅ **Benefits**

1. **Comprehensive Coverage**: More conditions = more questions
2. **Medical Accuracy**: Questions based on real patient experiences
3. **Simple Language**: Uses "fever" not "hyperthermia", etc.
4. **Structured Assessment**: Covers all 6 medical assessment categories

This ensures thorough diagnostic questioning while maintaining simplicity for patients.
