# Insulin Pump Settings Analyzer

This is my submission for **Llama Impact Hackathon London - Nov 2024** under **Area 2: Supporting Delivery of Public Services and Healthcare track**.

## About

A web application that analyzes insulin pump and CGM (Continuous Glucose Monitoring) data to provide personalized recommendations for pump settings optimization. The tool helps diabetes patients and healthcare providers by:

- Analyzing patterns in glucose levels and insulin delivery
- Suggesting specific adjustments to basal rates, carb ratios, and correction factors
- Providing clear explanations for recommendations
- Supporting data-driven decision making for diabetes management

## Features

- Upload and process insulin pump data files
- Interactive settings input interface
- AI-powered analysis using Llama-3.1-70B model provided by [Groq](https://console.groq.com/docs/overview)
- Clear, actionable recommendations
- Mobile-friendly design

## Technical Stack

- FastHTML for web interface
- Pandas for data processing
- LiteLLM for LLM integration
- Llama-3.1-70B model via [Groq](https://console.groq.com/docs/overview) for AI analysis

## License

This project is licensed under the [MIT License](LICENSE).
