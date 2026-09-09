// Money formatting for the whole storefront.
//
// The backend charges in the currency named by STRIPE_CURRENCY (inr), and each
// payment/invoice row carries its own currency code — so format from that
// rather than hardcoding a symbol. en-IN also gives the Indian digit grouping
// (₹1,59,900 rather than ₹159,900).
const CURRENCY = "INR";

export function formatMoney(amount, currency = CURRENCY) {
  const value = Number(amount ?? 0);
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency: (currency || CURRENCY).toUpperCase(),
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    // Unknown currency code from the API — show the amount with the code.
    return `${(currency || CURRENCY).toUpperCase()} ${value.toFixed(2)}`;
  }
}

// Whole-rupee variant for headline figures (dashboard stat tiles).
export function formatMoneyShort(amount, currency = CURRENCY) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: (currency || CURRENCY).toUpperCase(),
    maximumFractionDigits: 0,
  }).format(Number(amount ?? 0));
}
