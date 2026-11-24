export interface SegmentedOption<T extends string> {
  value: T;
  label: string;
  activeClassName?: string;
}

interface SegmentedControlProps<T extends string> {
  options: readonly (T | SegmentedOption<T>)[];
  value: T;
  onChange: (value: T) => void;
  ariaLabel: string;
  className?: string;
  buttonClassName?: string;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  className = '',
  buttonClassName = '',
}: SegmentedControlProps<T>) {
  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className={`flex items-center gap-1 p-1 bg-slate-100 rounded-md ${className}`}
    >
      {options.map((opt) => {
        const option = typeof opt === 'string' ? { value: opt, label: opt } : opt;
        const isActive = value === option.value;
        const activeClasses = option.activeClassName ?? 'bg-white text-slate-900 shadow-xs';
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={isActive}
            onClick={() => onChange(option.value)}
            className={`px-2.5 py-1 text-xs font-medium rounded-xs transition-colors whitespace-nowrap shrink-0 ${
              isActive ? activeClasses : 'text-slate-600 hover:text-slate-900'
            } ${buttonClassName}`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
