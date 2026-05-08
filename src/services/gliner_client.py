"""
GLiNER Client for Medical Entity Extraction
Zero-shot NER over drug / disease / symptom types.
"""

from typing import List, Optional
from loguru import logger

from src.config.settings import get_settings
from src.models.responses import Entity


class GLiNERClient:
    """Client for GLiNER-based medical entity extraction"""

    # Medical entity types to extract
    ENTITY_TYPES = ["drug", "disease", "symptom"]

    def __init__(
        self,
        model_name: Optional[str] = None,
        threshold: Optional[float] = None,
    ):
        """
        Initialize GLiNER client

        Args:
            model_name: HuggingFace model identifier for GLiNER.
                Falls back to settings.gliner_model.
            threshold: Default extraction confidence threshold (0-1).
                Falls back to settings.gliner_threshold.
        """
        settings = get_settings()
        self.model_name = model_name or settings.gliner_model
        self.threshold = threshold if threshold is not None else settings.gliner_threshold
        self._model = None
        self._loaded = False

    def _load_model(self):
        """Lazy load the GLiNER model"""
        if self._model is None:
            logger.info(f"Loading GLiNER model: {self.model_name}")
            try:
                from gliner import GLiNER
                self._model = GLiNER.from_pretrained(self.model_name)
                self._loaded = True
                logger.info("GLiNER model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load GLiNER model: {e}")
                raise

    async def close(self):
        """Clean up resources"""
        # GLiNER doesn't need explicit cleanup, but keep interface consistent
        self._model = None
        self._loaded = False
        logger.info("GLiNER client closed")

    async def health_check(self) -> dict:
        """Check if GLiNER is available"""
        try:
            if not self._loaded:
                self._load_model()

            if self._model is not None:
                return {
                    "status": "healthy",
                    "model": self.model_name,
                    "entity_types": self.ENTITY_TYPES
                }
            else:
                return {"status": "unhealthy", "error": "Model not loaded"}
        except Exception as e:
            logger.error(f"GLiNER health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    async def extract_entities(
        self,
        text: str,
        threshold: Optional[float] = None,
    ) -> List[Entity]:
        """
        Extract medical entities from text using GLiNER

        Args:
            text: Medical text to process
            threshold: Minimum confidence score (0-1). Defaults to the
                client-level threshold (settings.gliner_threshold).

        Returns:
            List of extracted Entity objects
        """
        try:
            # Lazy load model on first use
            if not self._loaded:
                self._load_model()

            logger.debug(f"Extracting entities from text: {text[:100]}...")

            effective_threshold = threshold if threshold is not None else self.threshold

            # GLiNER extraction
            predictions = self._model.predict_entities(
                text,
                self.ENTITY_TYPES,
                threshold=effective_threshold
            )

            entities = []
            for pred in predictions:
                # Capitalize type for consistency (drug -> Drug)
                entity_type = pred["label"].capitalize()

                # Generate a pseudo-CUI based on text (GLiNER doesn't provide CUIs)
                pseudo_cui = f"GLI_{entity_type.upper()}_{hash(pred['text'].lower()) % 100000:05d}"

                entities.append(Entity(
                    text=pred["text"],
                    cui=pseudo_cui,
                    name=pred["text"],  # GLiNER extracts the text directly
                    type=entity_type,
                    confidence=pred["score"],
                    start=pred.get("start"),
                    end=pred.get("end"),
                    negated=False  # GLiNER doesn't detect negation
                ))

            logger.info(f"Extracted {len(entities)} entities via GLiNER")
            return entities

        except Exception as e:
            logger.error(f"GLiNER extraction failed: {e}")
            raise


# Singleton instance
_gliner_client: Optional[GLiNERClient] = None


def get_gliner_client() -> GLiNERClient:
    """Get singleton GLiNER client instance"""
    global _gliner_client
    if _gliner_client is None:
        _gliner_client = GLiNERClient()
    return _gliner_client
