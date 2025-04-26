/**
 * KeroTrack UI Utility Functions
 * This file contains utility functions for UI updates with Socket.IO
 * The actual Socket.IO connection is established in the base template
 */

// Format data values with appropriate units
function formatValue(key, value) {
    if (value === null || value === undefined) return 'N/A';
    
    switch (key) {
        case 'percentage_remaining':
            return `${value.toFixed(1)}%`;
        case 'litres_remaining':
            return `${value.toFixed(1)}L`;
        case 'temperature':
            return `${value.toFixed(1)}°C`;
        case 'days_remaining':
            return `${Math.round(value)} days`;
        case 'empty_date':
            // Format date properly
            try {
                return new Date(value).toISOString().split('T')[0];
            } catch (e) {
                console.error("Invalid date format:", value);
                return "Invalid Date";
            }
        case 'remaining_value':
            return `£${value.toFixed(2)}`;
        case 'cost_to_fill':
            return `£${value.toFixed(2)}`;
        default:
            return value.toString();
    }
}

// Highlight a changed value with animation
function highlightElement(element) {
    element.classList.remove('highlight');
    // Trigger DOM reflow
    void element.offsetWidth;
    element.classList.add('highlight');
}

// Get appropriate CSS class for progress bars
function getProgressClass(key, value) {
    if (key === 'percentage_remaining') {
        if (value <= 15) return 'progress-low';
        if (value <= 40) return 'progress-medium';
        return 'progress-good';
    } 
    else if (key === 'days_remaining') {
        if (value <= 30) return 'progress-low';
        if (value <= 60) return 'progress-medium';
        return 'progress-good';
    }
    
    return 'progress-normal';
}

// Add debug logging (can be disabled in production)
function logDebug(message, data) {
    console.log(`[KeroTrack] ${message}`, data);
}

// Log any errors
function logError(message, error) {
    console.error(`[KeroTrack Error] ${message}`, error);
} 