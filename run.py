#!/usr/bin/env python3
"""
Development server runner for the Fertilizer Shop Dashboard API.
This ensures proper host binding for both local development and deployment.
"""
import os
import uvicorn

if __name__ == "__main__":
    # Get host and port from environment or use defaults
    host = os.getenv("HOST", "0.0.0.0")  # Bind to all interfaces
    port = int(os.getenv("PORT", 8000))
    
    # Run the server
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=True,  # Enable auto-reload for development
        log_level="info"
    )
