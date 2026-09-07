/* These mirror classify_health in backend/app/scoring.py. The dashboard used to carry its own
   numbers, which had drifted: metric cards turned amber below 85 while the API still called the
   model healthy, and the trend chart drew its warning line at 70 rather than the real boundary. */
export const HEALTHY_SCORE = 80
export const WARNING_SCORE = 65
