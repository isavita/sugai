from fasthtml.common import *
import os
import json
import zipfile
import pandas as pd
from litellm import completion

# Constants
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'zip'}

# LLM System Message
SYSTEM_MESSAGE = """You are a medical assistant providing concise CGM and insulin pump setting recommendations.

ANALYZE AND PROVIDE:
1. ONE specific pattern with exact time period and glucose values
2. ONE basal rate adjustment (single time block only)
3. Realistic, data-based outcome targets

FORMAT YOUR RESPONSE AS:
### Pattern Identified
- State exact time period and glucose values observed (e.g., "Between 2-5 AM: glucose consistently drops from 7.0 to 3.8 mmol/L")

### Recommended Change
- ONE specific basal rate adjustment for ONE time block
- Must include: current rate, new rate, exact start/end times

### Expected Outcome
- State specific, achievable glucose targets for the adjusted time period
- Avoid percentage predictions unless directly supported by the data

IMPORTANT:
- Focus on the most problematic time period only
- No overlapping time blocks
- Base predictions only on available data"""

# Initialize FastHTML app
app, rt = fast_app()

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_data_files(folder):
    """Process uploaded CSV files and return cleaned DataFrames"""
    alarms_data = pd.read_csv(f'{folder}/alarms_data_1.csv', skiprows=1)
    cgm_data = pd.read_csv(f'{folder}/cgm_data_1.csv', skiprows=1)
    bolus_data = pd.read_csv(f'{folder}/Insulin data/bolus_data_1.csv', skiprows=1)
    basal_data = pd.read_csv(f'{folder}/Insulin data/basal_data_1.csv', skiprows=1)

    # Clean up data
    alarms_exclude_values = [
        "tandem_cgm_sensor_expiring",
        "tandem_cgm_replace_sensor",
        "Cartridge Loaded",
        "Resume Pump Alarm (18A)"
    ]
    
    alarms_data = alarms_data.iloc[:, :-1]
    alarms_data_cleaned = alarms_data[~alarms_data['Alarm/Event'].isin(alarms_exclude_values)]
    cgm_data = cgm_data.iloc[:, :-1]
    bolus_data = bolus_data.iloc[:, :-3]
    basal_data = basal_data.iloc[:, :-2].drop(columns=["Percentage (%)"])
    
    return alarms_data_cleaned, cgm_data, bolus_data, basal_data

def generate_time_slots():
    """Generate 24 time slots for the form"""
    hours = []
    for hour in range(24):
        time = f"{hour:02d}:00"
        hours.append({
            "time": time,
            "basal_rate": 0.0,
            "correction_factor": "1:3.0",
            "carb_ratio": "1:10",
            "target_bg": 5.6
        })
    return hours

@rt("/")
def get():
    time_slots = generate_time_slots()
    
    form = Form(
        H1("Insulin Pump Settings Analyzer"),
        
        # File upload section
        Div(
            H2("Upload Data"),
            Input(type="file", name="file", accept=".zip"),
            cls="upload-section"
        ),
        
        # Settings input section
        Div(
            H2("Insulin Pump Settings"),
            Table(
                Tr(
                    Th("Time"),
                    Th("Basal Rate (U/hr)"),
                    Th("Correction Factor (1:mmol/L)"),
                    Th("Carb Ratio (1:grams)"),
                    Th("Target BG (mmol/L)")
                ),
                *[Tr(
                    Td(slot["time"]),
                    Td(Input(type="number", step="0.1", name=f"basal_rate_{i}", value=slot["basal_rate"])),
                    Td(Input(type="text", name=f"correction_factor_{i}", value=slot["correction_factor"])),
                    Td(Input(type="text", name=f"carb_ratio_{i}", value=slot["carb_ratio"])),
                    Td(Input(type="number", step="0.1", name=f"target_bg_{i}", value=slot["target_bg"]))
                ) for i, slot in enumerate(time_slots)]
            ),
            cls="settings-section"
        ),
        
        Button("Analyze", type="submit"),
        method="POST",
        enctype="multipart/form-data"
    )
    
    return Titled("Insulin Pump Settings Analyzer", form)

@rt("/")
async def post(req):
    # Create upload folder if it doesn't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Get the uploaded file
    file = req.files.get('file')
    if not file or not allowed_file(file.filename):
        return "Invalid file"
    
    # Save and extract zip file
    zip_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(zip_path)
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(UPLOAD_FOLDER)
    
    # Process the data
    try:
        alarms_data, cgm_data, bolus_data, basal_data = process_data_files(UPLOAD_FOLDER)
    except Exception as e:
        return f"Error processing files: {str(e)}"
    
    # Collect form data
    settings = []
    for i in range(24):
        settings.append({
            "time_range": f"{i:02d}:00",
            "basal_rate": float(req.form.get(f"basal_rate_{i}", 0)),
            "correction_factor": req.form.get(f"correction_factor_{i}", "1:3.0"),
            "carb_ratio": req.form.get(f"carb_ratio_{i}", "1:10"),
            "target_bg": float(req.form.get(f"target_bg_{i}", 5.6))
        })
    
    # Create user message for LLM
    user_message = f"""
    Current Insulin Pump Settings:
    {json.dumps({"timed_settings": settings}, indent=2)}
    
    Alarms Data:
    {alarms_data.to_string()}
    
    CGM Data:
    {cgm_data.to_string()}
    
    Bolus Data:
    {bolus_data.to_string()}
    
    Basal Data:
    {basal_data.to_string()}
    """
    
    # Get LLM recommendation
    response = completion(
        model="groq/llama-3.1-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": "```markdown"}
        ]
    )
    
    recommendation = response.choices[0].message.content
    
    return Titled("Analysis Results",
        Div(
            H1("Analysis Results"),
            Pre(recommendation),
            A("Back", href="/")
        )
    )

if __name__ == "__main__":
    serve()
