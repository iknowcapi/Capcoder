import React, { useEffect, useState } from "react";

const ASCII = `
   ____                _____          _      
  / ___|__ _ _ __     / ____|___   __| | ___ 
 | |   / _\` | '_ \\   | |    / _ \\ / _\` |/ _ \\
 | |__| (_| | |_) |  | |___| (_) | (_| |  __/
  \\____\\__,_| .__(_)  \\_____\\___/ \\__,_|\\___|
            |_|                              
`;

export const TerminalHero = ({ status }) => {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1200);
    return () => clearInterval(id);
  }, []);

  const date = new Date().toISOString().replace("T", " ").slice(0, 19);

  return (
    <header
      className="panel relative overflow-hidden p-4 sm:p-6 md:p-8"
      data-testid="terminal-hero"
      style={{ borderColor: "rgba(57,255,20,0.45)" }}
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between text-[10px] sm:text-xs label-xs text-neon_cyan neon-cyan">
          <span data-testid="hero-system-tag">[ SYS:CAPCODE // NODE-{(tick % 9) + 1} ]</span>
          <span className="hidden sm:inline">[ LOCAL://{date} UTC ]</span>
          <span>
            STATUS:{" "}
            <span className={!status ? "text-phosphor3" : "text-phosphor"}>
              {!status ? "BOOTING" : "ONLINE"}
            </span>
            <span className="animate-blink ml-1">_</span>
          </span>
        </div>

        <pre
          className="ascii text-phosphor neon-text text-[8px] sm:text-[10px] md:text-xs overflow-x-auto"
          aria-hidden
        >
{ASCII}
        </pre>

        <div className="font-bbs text-3xl sm:text-5xl lg:text-6xl uppercase tracking-widest text-phosphor neon-text leading-none">
          a bot that improves itself
        </div>
        <div className="font-bbs text-2xl sm:text-3xl lg:text-4xl uppercase tracking-widest text-neon_magenta neon-magenta leading-none glitch-on-hover">
          by building app-builders that build app-builders.
        </div>

        <div className="font-mono text-sm sm:text-base text-phosphor2 max-w-3xl mt-2">
          <span className="text-phosphor neon-text">capcode</span> — you type what you want built.
          the <span className="text-neon_cyan">Teacher bot</span> writes the brief, the{" "}
          <span className="text-neon_magenta">Artist bot</span> designs the product, and the code is
          materialized, executed, and delivered as a downloadable folder. no further human input.
        </div>

        <div className="flex flex-wrap gap-2 sm:gap-4 text-[10px] sm:text-xs label-xs mt-2">
          <span className="border border-phosphor/40 px-2 py-1 text-phosphor">
            CHAINS :: {status?.total_chains ?? "—"}
          </span>
          <span className="border border-neon_cyan/40 px-2 py-1 text-neon_cyan neon-cyan">
            {status?.providers?.openrouter ? "OPENROUTER" : "openrouter off"} ::{" "}
            {status?.providers?.nvidia ? "NVIDIA" : "nvidia off"} ::{" "}
            {status?.providers?.venice ? "VENICE" : "venice off"}
          </span>
          <span className="border border-neon_magenta/40 px-2 py-1 text-neon_magenta neon-magenta">
            HANDOFF :: AI → AI
          </span>
        </div>
      </div>
    </header>
  );
};
