// Single source of truth for how each role is presented in the UI, and what
// it actually grants — kept in sync with the backend's require_roles() checks
// so the interface never promises something the API will reject.
export const ROLE_META = {
  admin: {
    label: "Admin",
    color: "var(--role-admin)",
    soft: "var(--role-admin-soft)",
    tagline: "Full access — every protected operation in this store.",
    capabilities: [
      "Shop, buy, and pay like any customer",
      "Create, edit, and delete products",
      "See and manage every customer's orders",
      "See every payment and delete any of them",
      "See every invoice ever issued",
    ],
  },
  staff: {
    label: "Staff",
    color: "var(--role-staff)",
    soft: "var(--role-staff-soft)",
    tagline: "Runs the catalog and fulfils orders.",
    capabilities: [
      "Shop, buy, and pay like any customer",
      "Create, edit, and delete products",
      "See every order and update its status",
      "Confirm cash-on-delivery payments",
      "See only their own payments & invoices",
    ],
  },
  customer: {
    label: "Customer",
    color: "var(--role-customer)",
    soft: "var(--role-customer-soft)",
    tagline: "Shops the catalog and tracks their own orders.",
    capabilities: [
      "Browse products and manage a cart",
      "Check out with Stripe or cash on delivery",
      "Track their own order status live",
      "View their own payments",
      "View their own invoices",
    ],
  },
};

export const roleMeta = (role) => ROLE_META[role] || ROLE_META.customer;
export const canManageProducts = (role) => role === "admin" || role === "staff";
export const canManageOrders = (role) => role === "admin" || role === "staff";
export const isAdmin = (role) => role === "admin";
