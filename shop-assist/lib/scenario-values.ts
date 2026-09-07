/**
 * Produces a controlled wrong price for the contradiction demo.
 *
 * The value is derived from the selected product's real catalog price and the
 * prices already shown in this conversation. This keeps the scenario useful
 * for every product without assigning special demo prices to Nova (or any
 * other item).
 */
export function deriveContradictoryPrice(
  catalogPrice: number,
  previousAnswers: string[],
): number {
  const usedValues = new Set(
    previousAnswers
      .flatMap((answer) =>
        [...answer.matchAll(/\$\s?(\d+(?:\.\d{1,2})?)/g)].map((match) =>
          Number(match[1]),
        ),
      )
      .filter(Number.isFinite),
  );
  usedValues.add(catalogPrice);

  // Roughly seven percent, rounded to a natural $5 step and never below $5.
  const step = Math.max(5, Math.round((catalogPrice * 0.07) / 5) * 5);
  let candidate = catalogPrice + step;
  while (usedValues.has(candidate)) candidate += step;
  return candidate;
}
