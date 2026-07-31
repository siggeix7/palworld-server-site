import { IconArrowLeft, IconBrandGithub } from '@tabler/icons-react'

interface ProjectLinksProps {
  hidden: boolean
}

export function ProjectLinks({ hidden }: ProjectLinksProps) {
  return (
    <nav
      className={`pal-glass-surface absolute right-[354px] bottom-[18px] z-[18] flex h-11 items-center overflow-hidden transition-[opacity,transform] max-sm:right-3.5 max-sm:bottom-[68px] ${
        hidden ? 'pointer-events-none translate-y-2 opacity-0' : ''
      }`}
      aria-label="Navigazione mappa"
      aria-hidden={hidden}
      inert={hidden}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <a
        className="pal-interactive flex h-full min-h-11 items-center gap-2 border-r border-white/10 px-3 text-[#dff9fc] shadow-[inset_3px_0_#55d4e7] no-underline focus-visible:outline-none"
        href="/"
        aria-label="Torna all'Osservatorio"
        title="Torna al resto del sito"
      >
        <IconArrowLeft className="size-[19px] shrink-0" stroke={1.8} aria-hidden="true" focusable="false" />
        <span className="whitespace-nowrap text-[11px] font-semibold tracking-[.08em] uppercase max-[420px]:hidden">
          Torna all'Osservatorio
        </span>
        <span className="hidden whitespace-nowrap text-[11px] font-semibold tracking-[.08em] uppercase max-[420px]:inline">
          Sito
        </span>
      </a>
      <div className="flex h-full items-center gap-2 px-2.5 max-[500px]:px-2">
        <img
          className="size-7 shrink-0"
          src="/static/dashboard/live-map/favicon.svg"
          alt=""
          aria-hidden="true"
          draggable={false}
        />
        <span className="whitespace-nowrap text-xs tracking-[.025em] text-[#e2f3f5] max-[500px]:hidden">
          Palworld Live Map
        </span>
      </div>
      <a
        className="pal-interactive grid size-11 place-items-center border-l border-white/10 text-[#8bb8c1] focus-visible:outline-none"
        href="https://github.com/LukeHollandDev/palworld-live-map"
        target="_blank"
        rel="noreferrer"
        aria-label="Palworld Live Map on GitHub"
        title="View source on GitHub"
      >
        <IconBrandGithub className="size-[19px]" stroke={1.8} aria-hidden="true" focusable="false" />
        <span className="sr-only">Palworld Live Map on GitHub</span>
      </a>
    </nav>
  )
}
