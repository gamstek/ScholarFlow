interface StatusDotProps {
  status: 'pending' | 'active' | 'completed' | 'error';
  label: string;
}

/** 单个阶段圆点。 */
export function StatusDot({ status, label }: StatusDotProps) {
  const colors = {
    pending: 'bg-gray-200 text-gray-400',
    active: 'bg-blue-500 text-white',
    completed: 'bg-emerald-500 text-white',
    error: 'bg-red-500 text-white',
  };

  return (
    <span
      className={`inline-block px-3 py-1 rounded-full text-xs font-medium transition-colors duration-300 ${colors[status]}`}
    >
      {label}
    </span>
  );
}
