const GRADE_COLORS: Record<string, string> = {
  A: "bg-green-100 text-green-800 border-green-300",
  B: "bg-lime-100 text-lime-800 border-lime-300",
  C: "bg-yellow-100 text-yellow-800 border-yellow-300",
  D: "bg-orange-100 text-orange-800 border-orange-300",
  F: "bg-red-100 text-red-800 border-red-300",
  "N/A": "bg-gray-100 text-gray-500 border-gray-300",
  "Scan Incomplete": "bg-gray-100 text-gray-500 border-gray-300",
};

export function GradeBadge({ grade, size = "md" }: { grade: string; size?: "sm" | "md" | "lg" }) {
  const colors = GRADE_COLORS[grade] || GRADE_COLORS["N/A"];
  const sizeClasses = {
    sm: "text-lg px-2 py-0.5",
    md: "text-3xl px-4 py-2",
    lg: "text-6xl px-8 py-4",
  };

  return (
    <span className={`inline-block font-bold rounded-lg border-2 ${colors} ${sizeClasses[size]}`}>
      {grade}
    </span>
  );
}
