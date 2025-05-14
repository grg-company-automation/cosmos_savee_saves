from like_scanner.api import routes
from like_scanner.infra.drivers import savee_driver, cosmos_driver
import logging
from fastapi import FastAPI

# Import logging configuration to ensure structured log format is applied
# This module sets up logging format/project settings
from like_scanner.infra import logging_conf

# Initialize a logger for this module
logger = logging.getLogger("like_scanner.app")

# Create FastAPI application without Swagger UI or OpenAPI docs
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Import the Selenium driver initialization functions

# Include API routes from the like_scanner.api.routes module
app.include_router(routes.router)


@app.on_event("startup")
def on_startup():
    """Event handler for application startup: initialize Selenium drivers."""
    logger.info("Starting Like-Scanner API...")

    # Initialize Savee driver
    logger.info("Initializing Savee driver...")
    try:
        savee = savee_driver.init_driver()  # Launch headless Savee Selenium WebDriver
        app.state.driver_savee = savee
        logger.info("Savee driver ready.")
    except Exception as e:
        logger.exception("Failed to initialize Savee driver: %s", e)
        # If Savee driver fails to initialize, prevent startup (re-raise to halt application start)
        raise

    # Initialize Cosmos driver
    logger.info("Initializing Cosmos driver...")
    try:
        # Launch headless Cosmos Selenium WebDriver
        cosmos = cosmos_driver.init_cosmos_driver()
        app.state.driver_cosmos = cosmos
        logger.info("Cosmos driver ready.")
    except Exception as e:
        logger.exception("Failed to initialize Cosmos driver: %s", e)
        # Cleanup already initialized Savee driver before halting
        try:
            app.state.driver_savee.quit()
        except Exception:
            pass
        raise


@app.on_event("shutdown")
def on_shutdown():
    """Event handler for application shutdown: close Selenium drivers."""
    logger.info("Stopping Like-Scanner API...")

    # Close Savee driver if it was initialized
    savee = getattr(app.state, "driver_savee", None)
    if savee:
        logger.info("Closing Savee driver...")
        try:
            savee.quit()
            logger.info("Savee driver closed.")
        except Exception as e:
            logger.exception("Error while closing Savee driver: %s", e)

    # Close Cosmos driver if it was initialized
    cosmos = getattr(app.state, "driver_cosmos", None)
    if cosmos:
        logger.info("Closing Cosmos driver...")
        try:
            cosmos.quit()
            logger.info("Cosmos driver closed.")
        except Exception as e:
            logger.exception("Error while closing Cosmos driver: %s", e)
