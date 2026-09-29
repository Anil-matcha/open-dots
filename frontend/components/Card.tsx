export function Card({
  step,
  title,
  done,
  disabled,
  children,
}: {
  step: number;
  title: string;
  done?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      className={`rounded-lg border p-5 transition-opacity ${
        disabled
          ? "border-zinc-200 opacity-50 dark:border-zinc-800"
          : "border-zinc-200 dark:border-zinc-800"
      }`}
    >
      <div className="mb-3 flex items-center gap-2">
        <span
          className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-sm font-medium ${
            done
              ? "bg-emerald-600 text-white"
              : "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
          }`}
        >
          {done ? "✓" : step}
        </span>
        <h2 className="text-base font-semibold">{title}</h2>
      </div>
      <div className={disabled ? "pointer-events-none" : ""}>{children}</div>
    </section>
  );
}

export function ErrorText({ message }: { message: string | null }) {
  if (!message) return null;
  return <p className="mt-2 text-sm text-red-600 dark:text-red-400">{message}</p>;
}

export function Button({
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300"
    >
      {children}
    </button>
  );
}
