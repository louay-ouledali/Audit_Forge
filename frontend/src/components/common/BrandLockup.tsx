import { cn } from '@/lib/utils';
import { Hexagon, Network, Compass, Aperture } from 'lucide-react';

type SubService = 'lens' | 'connect' | 'discovery' | 'copilot';
type Size = 'sm' | 'md' | 'lg' | 'xl';

interface BrandLockupProps {
  service: SubService;
  size?: Size;
  className?: string;
  hideText?: boolean;
}

const CONFIG = {
  lens: {
    name: 'Forge Lens',
    icon: Aperture,
    bgClasses: 'bg-ey-yellow/10 border-ey-yellow/20 text-ey-yellow',
    iconShadow: 'drop-shadow-[0_0_8px_rgba(255,230,0,0.5)]',
    textGradient: 'from-ey-yellow to-amber-200'
  },
  connect: {
    name: 'Forge Connect',
    icon: Network,
    bgClasses: 'bg-ey-yellow/10 border-ey-yellow/20 text-ey-yellow',
    iconShadow: 'drop-shadow-[0_0_8px_rgba(255,230,0,0.5)]',
    textGradient: 'from-ey-yellow to-amber-200'
  },
  discovery: {
    name: 'Forge Discovery',
    icon: Compass,
    bgClasses: 'bg-ey-yellow/10 border-ey-yellow/20 text-ey-yellow',
    iconShadow: 'drop-shadow-[0_0_8px_rgba(255,230,0,0.5)]',
    textGradient: 'from-ey-yellow to-amber-200'
  },
  copilot: {
    name: 'Forge Co-Pilot',
    icon: Hexagon,
    bgClasses: 'bg-ey-yellow/10 border-ey-yellow/20 text-ey-yellow',
    iconShadow: 'drop-shadow-[0_0_8px_rgba(255,230,0,0.5)]',
    textGradient: 'from-ey-yellow to-amber-200'
  }
};

const SIZES = {
  sm: { iconBox: 'h-6 w-6 rounded-md', icon: 'h-3.5 w-3.5', text: 'text-xs' },  
  md: { iconBox: 'h-8 w-8 rounded-lg', icon: 'h-4 w-4', text: 'text-sm' },      
  lg: { iconBox: 'h-10 w-10 rounded-xl', icon: 'h-5 w-5', text: 'text-base' },  
  xl: { iconBox: 'h-14 w-14 rounded-2xl', icon: 'h-7 w-7', text: 'text-2xl' }   
};

export default function BrandLockup({ service, size = 'md', className, hideText = false }: BrandLockupProps) {
  const conf = CONFIG[service];
  const s = SIZES[size];
  const Icon = conf.icon;

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div className={cn(
        "flex items-center justify-center border shadow-sm transition-all",
        s.iconBox,
        conf.bgClasses,
        conf.iconShadow
      )}>
        <Icon className={s.icon} />
      </div>
      {!hideText && (
        <span className={cn(
          "font-bold tracking-tight bg-clip-text text-transparent bg-gradient-to-r",
          s.text,
          conf.textGradient
        )}>
          {conf.name}
        </span>
      )}
    </div>
  );
}
