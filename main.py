from fasthtml.common import *
import os
import json
import zipfile
import pandas as pd
from litellm import completion
from datetime import datetime

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

# Constants and default settings
DEFAULT_SETTINGS = json.loads("""
{
  "timed_settings": [
    {"time_range": "12:00 AM", "basal_rate": 0.4, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 6.5},
    {"time_range": "2:00 AM", "basal_rate": 0.5, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 6.5},
    {"time_range": "5:00 AM", "basal_rate": 0.8, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 6.5},
    {"time_range": "6:00 AM", "basal_rate": 0.9, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 6.5},
    {"time_range": "7:00 AM", "basal_rate": 0.8, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "8:00 AM", "basal_rate": 0.8, "correction_factor": "1:2.5", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "9:00 AM", "basal_rate": 0.45, "correction_factor": "1:2.5", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "3:00 PM", "basal_rate": 0.5, "correction_factor": "1:2.5", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "4:00 PM", "basal_rate": 0.6, "correction_factor": "1:2.5", "carb_ratio": "1:10", "target_bg": 5.6},
    {"time_range": "7:00 PM", "basal_rate": 0.45, "correction_factor": "1:2.5", "carb_ratio": "1:12", "target_bg": 5.6},
    {"time_range": "9:00 PM", "basal_rate": 0.3, "correction_factor": "1:3.0", "carb_ratio": "1:12", "target_bg": 5.6},
    {"time_range": "11:00 PM", "basal_rate": 0.3, "correction_factor": "1:3.0", "carb_ratio": "1:10", "target_bg": 5.6}
  ]
}
""")

def parse_time(time_str):
    """Convert time string to 24-hour format integer"""
    try:
        if 'AM' in time_str or 'PM' in time_str:
            return int(datetime.strptime(time_str, "%I:%M %p").strftime("%H"))
        return int(datetime.strptime(time_str, "%H:%M").strftime("%H"))
    except ValueError:
        return None

def format_time(hour):
    """Convert hour to AM/PM format"""
    return datetime.strptime(f"{hour:02d}:00", "%H:%M").strftime("%I:%M %p").lstrip("0")

def convert_settings_to_hourly():
    """Convert default settings to hourly format with proper ordering"""
    hourly_settings = {}
    
    # Convert all times to 24-hour format and store settings
    for setting in DEFAULT_SETTINGS["timed_settings"]:
        hour = parse_time(setting["time_range"])
        if hour is not None:
            hourly_settings[hour] = {
                "basal_rate": setting["basal_rate"],
                "correction_factor": setting["correction_factor"],
                "carb_ratio": setting["carb_ratio"],
                "target_bg": setting["target_bg"]
            }
    
    return hourly_settings

def generate_settings_table():
    """Generate the settings table with default values and proper ordering"""
    hourly_settings = convert_settings_to_hourly()
    
    # Create table rows
    rows = []
    
    # Add header row
    rows.append(Tr(
        Th("Time"),
        Th("Basal Rate (U/hr)"),
        Th("Correction Factor (1:mmol/L)"),
        Th("Carb Ratio (1:grams)"),
        Th("Target BG (mmol/L)"),
        Th("Actions")
    ))
    
    # Get the last settings for filling gaps
    last_settings = {
        "basal_rate": 0.0,
        "correction_factor": "1:3.0",
        "carb_ratio": "1:10",
        "target_bg": 5.6
    }
    
    # Generate rows for each hour, using previous settings for missing hours
    for hour in range(24):
        if hour in hourly_settings:
            last_settings = hourly_settings[hour]
            
        rows.append(Tr(
            Td(format_time(hour)),
            Td(Input(type="number", step="0.1", name=f"basal_rate_{hour}", 
                    value=str(last_settings["basal_rate"]))),
            Td(Input(type="text", name=f"correction_factor_{hour}", 
                    value=last_settings["correction_factor"])),
            Td(Input(type="text", name=f"carb_ratio_{hour}", 
                    value=last_settings["carb_ratio"])),
            Td(Input(type="number", step="0.1", name=f"target_bg_{hour}", 
                    value=str(last_settings["target_bg"]))),
            Td(
                Button("Delete", 
                      type="button",
                      onclick=f"deleteRow(this)",
                      cls="delete-btn"),
                style="text-align: center;"
            )
        ))
    
    # Create and return the table with all rows
    return Table(*rows, cls="settings-table")

# Add custom CSS for the insulin pump settings
CUSTOM_CSS = """
/* Compact table styles */
.settings-table {
    width: auto;
    margin: 0 auto;
    border-collapse: collapse;
}

.settings-table th, .settings-table td {
    padding: 0.3em;
    text-align: left;
}

.settings-table input {
    width: 6em;
    padding: 0.2em;
    margin: 0;
    height: 2em;
}

.delete-btn {
    padding: 0.2em 0.5em;
    background-color: #ff4444;
    color: white;
    border: none;
    border-radius: 3px;
    cursor: pointer;
}

.delete-btn:hover {
    background-color: #cc0000;
}

/* Container styles */
.content-container {
    max-width: 1000px;
    margin: 0 auto;
    padding: 1em;
}

/* Form styles */
.settings-form {
    background: var(--background-color);
    padding: 1em;
    border-radius: 4px;
}
"""

# Add JavaScript for row management
CUSTOM_JS = """
function deleteRow(button) {
    const row = button.closest('tr');
    if (document.querySelectorAll('.settings-table tr').length > 2) {
        row.remove();
    } else {
        alert('Cannot delete the last row');
    }
}

function validateForm() {
    const rows = document.querySelectorAll('.settings-table tr');
    const times = new Set();
    
    for (let i = 1; i < rows.length; i++) {
        const timeCell = rows[i].cells[0];
        const time = timeCell.textContent;
        
        if (times.has(time)) {
            alert('Duplicate time entries are not allowed');
            return false;
        }
        times.add(time);
    }
    
    if (rows.length > 25) { // Header + 24 hours
        alert('Maximum 24 time slots allowed');
        return false;
    }
    
    return true;
}
"""

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

@rt("/")
def get():
    form = Form(
        Div(
            H2("Upload Data"),
            Input(type="file", name="file", accept=".zip"),
            cls="upload-section"
        ),
        Div(
            H2("Insulin Pump Settings"),
            generate_settings_table(),
            cls="settings-form"
        ),
        Button("Analyze", type="submit", onclick="return validateForm()"),
        method="POST",
        enctype="multipart/form-data",
        cls="content-container"
    )
    
    return Titled("Insulin Pump Settings Analyzer",
        Style(CUSTOM_CSS),
        Script(CUSTOM_JS),
        form
    )

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
