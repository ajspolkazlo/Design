export const CATEGORIES = [
  { id: "general", label: "General", icon: "🧾" },
  { id: "food", label: "Food & Drink", icon: "🍕" },
  { id: "groceries", label: "Groceries", icon: "🛒" },
  { id: "transport", label: "Transport", icon: "🚕" },
  { id: "rent", label: "Rent", icon: "🏠" },
  { id: "utilities", label: "Utilities", icon: "💡" },
  { id: "entertainment", label: "Entertainment", icon: "🎬" },
  { id: "travel", label: "Travel", icon: "✈️" },
  { id: "shopping", label: "Shopping", icon: "🛍️" },
  { id: "health", label: "Health", icon: "💊" },
] as const;

export type CategoryId = (typeof CATEGORIES)[number]["id"];

export function categoryIcon(id: string): string {
  return CATEGORIES.find((c) => c.id === id)?.icon ?? "🧾";
}

export function categoryLabel(id: string): string {
  return CATEGORIES.find((c) => c.id === id)?.label ?? "General";
}
