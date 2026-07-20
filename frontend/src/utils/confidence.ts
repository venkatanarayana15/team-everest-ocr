/**
 * Shared confidence color utility
 * Single source of truth for confidence-based color coding across all components
 */

/**
 * Returns the color for a given confidence value (0-100)
 * Green (>= 80): High confidence
 * Red (< 80): Low confidence / needs review
 */
export function confidenceColor(conf: number): string {
  if (conf >= 80) return '#16a34a'; // Green
  return '#dc2626'; // Red
}

/**
 * Returns the color for a given confidence value (0-100) with 3 tiers
 * Green (>= 80): High confidence
 * Amber (>= 50): Medium confidence
 * Red (< 50): Low confidence
 * 
 * @deprecated Use confidenceColor() instead for binary green/red
 */
export function confidenceColor3Tier(conf: number): string {
  if (conf >= 80) return '#16a34a'; // Green
  if (conf >= 50) return '#d97706'; // Amber
  return '#dc2626'; // Red
}

/**
 * Returns a CSS class name for confidence-based styling
 */
export function confidenceClass(conf: number): string {
  if (conf >= 80) return 'confidence-high';
  return 'confidence-low';
}

/**
 * Returns a human-readable label for confidence level
 */
export function confidenceLabel(conf: number): string {
  if (conf >= 80) return 'High';
  return 'Low';
}

/**
 * Returns the confidence threshold for "high" confidence
 */
export const HIGH_CONFIDENCE_THRESHOLD = 80;

/**
 * Returns the confidence threshold for "medium" confidence (3-tier only)
 */
export const MEDIUM_CONFIDENCE_THRESHOLD = 50;