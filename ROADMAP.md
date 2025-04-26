## Roadmap for Domestic Heating Oil Monitoring

This document outlines the planned features and enhancements for the Domestic Heating Oil Monitoring project, organised into phases and categories for clarity.

---

### Phase 1 (1–3 months)
- **Gotify Notifications**: integrate threshold alerts via Gotify for low‑oil warnings and refill reminders
- **MQTT Topic Viewer**: add a raw JSON viewer in the web UI to inspect messages on specific MQTT topics in real time
- **Web Security Fundamentals**: implement authentication for the web interface and secure configuration management
- **Data Protection**: fix SQL injection vulnerabilities and add CSRF protection to all forms

---

### Phase 2 (3–6 months)
- **Mobile‑Responsive UI**: refine dashboard layout for smartphones and tablets
- **Data Export**: enable CSV and JSON downloads of historical data for custom offline analysis
- **Input Validation**: enhance form submissions with proper input validation and sanitization
- **Secure Communications**: enable TLS/SSL for MQTT connections and improve credential management
- **Error Handling**: implement proper error pages without exposing implementation details

---

## Future Enhancements
- **Multi‑Tank Support**: monitor and manage multiple heating oil tanks from a single interface
- **Leak Detection Improvements**: enhance anomaly detection for potential leaks and system faults
- **Smart Thermostat Integration**: connect with third‑party thermostats (e.g. Nest, Tado) to automate heating adjustments based on tank levels
- **Smart Refill Scheduler**: suggest optimal refill dates based on forecasts, weather data, and delivery slot availability
- **Volume Calculation Accuracy**: Revisit and enhance the calculation of remaining oil volume. Explore advanced smoothing/filtering techniques, improved handling of sensor jitter, and consider additional environmental corrections (e.g., temperature, sensor calibration, or tank deformation) to further improve day-to-day and long-term accuracy.
- **Advanced Security Features**: implement rate limiting, access control for record management, and security event monitoring
- **Dependency Management**: establish automated updating of dependencies to maintain security patches
- **Centralized Database Management**: refactor database operations into a dedicated module that manages schema, migrations, and queries centrally. Separate SQL operations from business logic to improve maintainability, security, and facilitate easier implementation of features like multi-tank support.

---

## AI Integration (via OpenAI API)
1. **Natural‑Language Queries**: let users ask questions like "How much oil did I use last winter?" and get instant answers
2. **AI‑Powered Reports**: generate monthly summaries in plain English covering usage, costs, CO₂ emissions and efficiency
3. **Smart Refill Suggestions**: use forecast data and weather APIs with the OpenAI API to recommend the best day for a refill, minimising costs and risks
4. **Security Analysis**: leverage AI to analyze system logs and identify potential security threats or unusual access patterns

---
