"use client";

export default function DeleteButton({
  action,
  label = "Delete",
  confirmText = "Delete this? This can't be undone.",
}: {
  action: () => Promise<void>;
  label?: string;
  confirmText?: string;
}) {
  return (
    <form
      action={action}
      onSubmit={(e) => {
        if (!window.confirm(confirmText)) e.preventDefault();
      }}
    >
      <button
        type="submit"
        className="rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-negative"
      >
        {label}
      </button>
    </form>
  );
}
