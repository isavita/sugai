from fasthtml.common import *
import os
import json
import zipfile
import pandas as pd
from litellm import completion
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'zip'}

# LLM System Message
SYSTEM_MESSAGE = """You are a medical assistant providing concise CGM and insulin pump setting recommendations.

ANALYZE AND PROVIDE:
1. ONE specific pattern with exact time period and glucose values
2. ONE basal rate adjustment (single time block only)
3. Realistic, data-based outcome targets
4. Format all time references using AM/PM (e.g., "2:00 AM" instead of "02:00")


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
    .settings-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;  /* Smaller font size */
    }
    
    .settings-table th,
    .settings-table td {
        padding: 4px 8px;  /* Reduced padding */
        border: 1px solid #ddd;
    }
    
    .settings-table input {
        width: 100%;
        padding: 2px 4px;  /* Smaller input fields */
        height: 24px;      /* Reduced height */
        margin: 0;
    }
    
    .delete-btn {
        padding: 2px 8px;
        font-size: 12px;
        height: auto;
    }
    
    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .settings-table {
            font-size: 12px;  /* Even smaller on mobile */
        }
        
        .settings-table th,
        .settings-table td {
            padding: 2px 4px;
        }
        
        .content-container {
            padding: 10px;
            margin: 0;
        }
        
        .settings-form {
            overflow-x: auto;  /* Allow horizontal scroll on mobile */
        }
        
        /* Stack the upload and settings sections on mobile */
        .upload-section,
        .settings-form {
            width: 100%;
            margin-bottom: 1em;
        }
    }
    
    .back-button {
        display: inline-block;
        margin-top: 1em;
        padding: 0.5em 1em;
        background-color: #f0f0f0;
        color: #333;
        text-decoration: none;
        border-radius: 4px;
        border: 1px solid #ddd;
    }
    
    .back-button:hover {
        background-color: #e0e0e0;
    }
    
    @media (max-width: 768px) {
        .back-button {
            width: 100%;
            text-align: center;
            margin-bottom: 1em;
        }
    }
    
    .analysis-results {
        max-width: 800px;  /* Limit width on larger screens */
        margin: 2em auto;  /* Center the results and add vertical spacing */
        padding: 1.5em;    /* Add padding around content */
        background: #f8f9fa;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .analysis-results h3 {
        color: #2c3e50;
        margin-bottom: 1em;
    }
    
    .analysis-results pre {
        white-space: pre-wrap;       /* Wrap text instead of scrolling */
        word-wrap: break-word;       /* Break long words */
        padding: 1em;
        background: #fff;
        border: 1px solid #e9ecef;
        border-radius: 4px;
        font-size: 0.9em;
        line-height: 1.5;
        overflow-x: auto;            /* Add scroll only if needed */
        max-width: 100%;             /* Ensure it doesn't overflow container */
    }
    
    .back-button {
        display: inline-block;
        margin-top: 1.5em;
        padding: 0.5em 1em;
        background-color: #f0f0f0;
        color: #333;
        text-decoration: none;
        border-radius: 4px;
        border: 1px solid #ddd;
        transition: background-color 0.2s;
    }
    
    .back-button:hover {
        background-color: #e0e0e0;
    }
    
    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .analysis-results {
            margin: 1em;
            padding: 1em;
        }
        
        .analysis-results pre {
            font-size: 0.85em;
            padding: 0.75em;
        }
        
        .back-button {
            display: block;
            text-align: center;
            margin: 1em auto;
        }
    }
    
    .upload-section input[type="file"] {
        padding: 8px;
        margin-bottom: 1em;
        border: 2px dashed #ccc;
        border-radius: 4px;
        width: 100%;
        background: #f8f9fa;
    }
    
    .upload-section input[type="file"]:hover {
        border-color: #0056b3;
        background: #f0f4f8;
    }
    
    .settings-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
        background: white;  /* Make table stand out more */
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);  /* Subtle shadow */
    }
    
    .settings-table th,
    .settings-table td {
        padding: 4px 8px;
        border: 1px solid #e0e0e0;  /* Lighter border color */
    }
    
    .settings-table th {
        background: #f8f9fa;  /* Light header background */
        color: #2c3e50;       /* Darker text for contrast */
    }
    
    .settings-table input {
        width: 100%;
        padding: 2px 4px;
        height: 24px;
        margin: 0;
        border: 1px solid #dee2e6;
        border-radius: 3px;
    }
    
    .settings-table input:focus {
        outline: none;
        border-color: #0056b3;
        box-shadow: 0 0 0 2px rgba(0,86,179,0.1);
    }
    
    .delete-btn {
        padding: 2px 8px;
        font-size: 12px;
        height: auto;
        background: #dc3545;
        color: white;
        border: none;
        border-radius: 3px;
        cursor: pointer;
    }
    
    .delete-btn:hover {
        background: #c82333;
    }
    
    button[type="submit"] {
        width: 100%;
        padding: 10px;
        background: #0056b3;
        color: white;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-size: 16px;
        margin-top: 1em;
    }
    
    button[type="submit"]:hover {
        background: #004494;
    }
    
    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .settings-table {
            font-size: 12px;
        }
        
        .settings-table th,
        .settings-table td {
            padding: 2px 4px;
        }
        
        .content-container {
            padding: 10px;
            margin: 0;
        }
        
        .settings-form {
            overflow-x: auto;
        }
        
        .upload-section,
        .settings-form {
            width: 100%;
            margin-bottom: 1em;
        }
    }
    
    .upload-section {
        text-align: center;
        margin: 2em auto;
        max-width: 600px;
    }
    
    .upload-section input[type="file"] {
        display: none;  /* Hide the default file input */
    }
    
    .file-upload-label {
        display: inline-block;
        padding: 10px 20px;
        background: #0056b3;
        color: white;
        border-radius: 4px;
        cursor: pointer;
        transition: background-color 0.2s;
    }
    
    .file-upload-label:hover {
        background: #004494;
    }
    
    .file-name {
        margin-top: 8px;
        color: #666;
    }
    
    .analysis-results {
        max-width: 800px;
        margin: 2em auto;
        padding: 2em;
        background: white;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
    
    .analysis-results h3 {
        color: #2c3e50;
        margin-bottom: 1.5em;
        padding-bottom: 0.5em;
        border-bottom: 2px solid #eee;
    }
    
    .analysis-results pre {
        white-space: pre-wrap;
        word-wrap: break-word;
        padding: 1.5em;
        background: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 6px;
        font-size: 0.95em;
        line-height: 1.6;
    }
    
    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .analysis-results {
            margin: 1em;
            padding: 1em;
        }
        
        .analysis-results pre {
            padding: 1em;
            font-size: 0.9em;
        }
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
app, rt = fast_app(hdrs=(
    Script(src="https://unpkg.com/htmx.org@1.9.10"),
    Style(CUSTOM_CSS)
))

# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def process_zip_data(file_path, folder_path):
    """Process the uploaded zip file and return raw dataframes"""
    try:
        # Extract the zip file
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            logger.info(f"Extracting zip file to {folder_path}")
            zip_ref.extractall(folder_path)
        
        # Read raw data
        data = {
            'alarms': pd.read_csv(f'{folder_path}/alarms_data_1.csv', skiprows=1),
            'cgm': pd.read_csv(f'{folder_path}/cgm_data_1.csv', skiprows=1),
            'bolus': pd.read_csv(f'{folder_path}/Insulin data/bolus_data_1.csv', skiprows=1),
            'basal': pd.read_csv(f'{folder_path}/Insulin data/basal_data_1.csv', skiprows=1)
        }
        
        logger.info("Successfully loaded raw data files")
        return data
        
    except Exception as e:
        logger.error(f"Error processing zip file: {str(e)}")
        raise

def clean_data(data):
    """Clean and process the raw dataframes"""
    try:
        logger.info("Starting data cleaning process...")
        
        # Clean alarms data
        alarms_data = data['alarms'].iloc[:, :-1]  # remove Serial Number column
        alarms_exclude_values = [
            "tandem_cgm_sensor_expiring",
            "tandem_cgm_replace_sensor",
            "Cartridge Loaded",
            "Resume Pump Alarm (18A)"
        ]
        alarms_data = alarms_data[~alarms_data['Alarm/Event'].isin(alarms_exclude_values)]
        
        # Clean CGM data
        cgm_data = data['cgm'].iloc[:, :-1]  # remove Serial Number column
        
        # Clean bolus data
        bolus_data = data['bolus'].iloc[:, :-3]  # remove last 3 columns
        
        # Clean basal data
        basal_data = data['basal'].iloc[:, :-2]  # remove last two columns
        basal_data = basal_data.drop(columns=["Percentage (%)"])
        basal_data = basal_data.sort_values(by="Timestamp", ascending=False)
        
        cleaned_data = {
            'alarms': alarms_data,
            'cgm': cgm_data,
            'bolus': bolus_data,
            'basal': basal_data
        }
        
        logger.info("Data cleaning completed successfully")
        return cleaned_data
        
    except Exception as e:
        logger.error(f"Error cleaning data: {str(e)}")
        raise

@rt("/")
def get():
    form = Form(
        Div(
            H2("Upload Data"),
            Label(
                "Choose File",
                Input(type="file", name="file", accept=".zip", id="file-input"),
                cls="file-upload-label"
            ),
            Div(cls="file-name", id="file-name-display"),
            cls="upload-section"
        ),
        Div(
            H2("Insulin Pump Settings"),
            generate_settings_table(),
            cls="settings-form"
        ),
        Button("Analyze", type="submit"),
        Div(id="analysis-results", cls="analysis-results", style="display: none;"),
        method="POST",
        action="/"  # Post to same URL
    )
    
    return Titled("Insulin Pump Settings Analyzer", 
        form,
        Script("""
            document.getElementById('file-input').addEventListener('change', function() {
                var fileName = this.files[0] ? this.files[0].name : 'No file chosen';
                document.getElementById('file-name-display').textContent = fileName;
            });
        """)
    )

@rt("/", methods=["POST"])
async def post(req):
    try:
        form = await req.form()
        file = form.get('file')
        
        if not file:
            return Div("No file uploaded", cls="error-message")
            
        logger.info(f"Processing analysis request for file: {file.filename}")
        
        # Create unique folder for this upload
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder_path = os.path.join(UPLOAD_FOLDER, timestamp)
        os.makedirs(folder_path, exist_ok=True)
        
        try:
            # Save uploaded file
            file_path = os.path.join(folder_path, file.filename)
            contents = await file.read()
            with open(file_path, 'wb') as f:
                f.write(contents)
            
            # Process and clean data
            raw_data = process_zip_data(file_path, folder_path)
            data = clean_data(raw_data)
            
            # Collect settings from form
            settings = []
            for i in range(24):
                settings.append({
                    "time_range": f"{i:02d}:00",
                    "basal_rate": float(form.get(f"basal_rate_{i}", 0)),
                    "correction_factor": form.get(f"correction_factor_{i}", "1:3.0"),
                    "carb_ratio": form.get(f"carb_ratio_{i}", "1:10"),
                    "target_bg": float(form.get(f"target_bg_{i}", 5.6))
                })
            
            # Create user message with legend
            user_message = f"""
            I am providing data from my insulin pump and CGM system to help me optimize my personal insulin profile. Below are my current insulin pump settings that I would like reviewed based on the following data:

            ### Current Insulin Pump Settings:
            {json.dumps({"timed_settings": settings}, indent=2)}

            ### Alarms Data:
            {data['alarms'].to_string(index=False)}

            #### Legend of Alarm/Event Terms:
            - **tandem_cgm_low**: Indicates that glucose levels have dropped below a preset threshold.
            - **tandem_cgm_low_2**: A repeated or escalated low glucose alarm, indicating that glucose levels are critically low or have stayed low for an extended period.
            - **tandem_cgm_high**: Indicates that glucose levels have risen above a preset threshold, typically signaling hyperglycemia.

            ### CGM Data:
            {data['cgm'].to_string(index=False)}

            ### Bolus Data:
            {data['bolus'].to_string(index=False)}

            ### Basal Data:
            {data['basal'].to_string(index=False)}

            #### Legend of Insulin Types in Basal Data:
            - **Suspend**: Indicates that insulin delivery has been temporarily stopped, usually due to low glucose levels or other safety concerns.
            - **Scheduled**: Represents the basal insulin that is pre-programmed to be delivered continuously in the background.
            - **Temporary**: Indicates an adjustment to the basal rate for a temporary period, often used during exercise or other activities affecting insulin needs.

            Using all of the provided data, please suggest personalized adjustments to my current insulin pump settings, including basal rates, carb ratios, and correction factors, in order to improve my glucose control and reduce the frequency of alarms.
            """
            
            logger.info("Sending prompt to LLM for analysis")
            logger.debug(f"LLM Prompt:\n{user_message}")
            
            # Get LLM recommendation
            response = completion(
                model="groq/llama-3.1-70b-versatile",
                temperature=0.0,
                stop=["```"],
                messages=[
                    {"role": "system", "content": SYSTEM_MESSAGE},
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": "```markdown"}
                ]
            )
            
            recommendation = response.choices[0].message.content
            
            return Div(
                H3("Analysis Results"),
                Pre(recommendation),
                A("Back", href="/", cls="back-button"),
                cls="analysis-results"
            )
            
        finally:
            # Clean up uploaded files
            if os.path.exists(file_path):
                os.remove(file_path)
                
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        return Div(
            P(f"An error occurred: {str(e)}"),
            A("Back", href="/", cls="back-button"),
            cls="error-message"
        )

if __name__ == "__main__":
    serve()
