"use client";

interface FooterProps {
  compact?: boolean;
}

export function Footer({ compact }: FooterProps) {
  if (compact) {
    return (
      <footer className="py-4 text-center text-xs text-gray-400">
        Built by{" "}
        <a href="https://pranavdhingra.com" target="_blank" rel="noopener noreferrer" className="text-gray-500 hover:text-gray-700 underline underline-offset-2">
          Pranav Dhingra
        </a>
        {" & "}
        <a href="https://www.linkedin.com/in/tishyakhanna9/" target="_blank" rel="noopener noreferrer" className="text-gray-500 hover:text-gray-700 underline underline-offset-2">
          Tishya Khanna
        </a>
        <span className="mx-2 text-gray-300">|</span>
        <a href="https://github.com/pcatattacks/agent-probe" target="_blank" rel="noopener noreferrer" className="text-gray-500 hover:text-gray-700 inline-flex items-center gap-1">
          <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
          GitHub
        </a>
      </footer>
    );
  }

  return (
    <footer className="mt-12 pt-6 border-t border-gray-100">
      <div className="flex flex-col items-center gap-3">
        <div className="flex items-center gap-4 text-sm text-gray-500">
          <span>Built by</span>
          <a href="https://pranavdhingra.com" target="_blank" rel="noopener noreferrer" className="text-gray-700 font-medium hover:text-blue-600 transition-colors">
            Pranav Dhingra
          </a>
          <span className="text-gray-300">&</span>
          <a href="https://www.linkedin.com/in/tishyakhanna9/" target="_blank" rel="noopener noreferrer" className="text-gray-700 font-medium hover:text-blue-600 transition-colors">
            Tishya Khanna
          </a>
        </div>
        <div className="flex items-center gap-4">
          <a
            href="https://github.com/pcatattacks/agent-probe"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-600 bg-gray-50 border border-gray-200 rounded-md hover:bg-gray-100 hover:text-gray-900 transition-colors"
          >
            <svg className="w-4 h-4" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
            Star on GitHub
          </a>
        </div>
      </div>
    </footer>
  );
}
