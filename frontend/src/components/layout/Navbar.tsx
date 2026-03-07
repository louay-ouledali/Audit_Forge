import { Link, useLocation } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
    LayoutDashboard,
    Building2,
    FileText,
    BarChart3,
    Settings,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import logoImg from '../../assets/logo.png';

const navItems = [
    { label: 'Dashboard', icon: LayoutDashboard, path: '/' },
    { label: 'Clients', icon: Building2, path: '/clients' },
    { label: 'Benchmarks', icon: FileText, path: '/benchmarks' },
    { label: 'Reports', icon: BarChart3, path: '/reports' },
    { label: 'Settings', icon: Settings, path: '/settings' },
];

const pageTitles: Record<string, string> = {
    '/': 'Dashboard',
    '/clients': 'Clients',
    '/benchmarks': 'Benchmarks',
    '/reports': 'Reports',
    '/settings': 'Settings',
};

export default function Navbar() {
    const location = useLocation();

    const title = pageTitles[location.pathname] ??
        (location.pathname.startsWith('/clients/') ? 'Client Workspace' :
            location.pathname.startsWith('/missions/') && location.pathname.includes('/analysis') ? 'AI Analysis' :
                location.pathname.startsWith('/missions/') ? 'Mission Workspace' :
                    location.pathname.startsWith('/benchmarks/') ? 'Benchmark Detail' :
                        location.pathname.startsWith('/findings/') ? 'Finding Detail' :
                            'AuditForge');

    return (
        <div className="fixed top-0 left-0 right-0 z-50 flex justify-center p-4 py-6 pointer-events-none">
            <nav aria-label="Main navigation" className="pointer-events-auto flex items-center gap-6 rounded-full border border-dark-border/50 bg-dark-surface/60 px-6 py-2.5 backdrop-blur-md shadow-[0_8px_32px_rgba(0,0,0,0.5)] transition-all hover:border-dark-border hover:bg-dark-surface/80 hover:shadow-[0_8px_32px_rgba(255,230,0,0.1)]">

                {/* Logo and Context */}
                <div className="flex items-center gap-3 pr-6 border-r border-dark-border/50">
                    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ey-yellow/10 ring-1 ring-ey-yellow/30 shadow-[0_0_10px_rgba(255,230,0,0.2)] overflow-hidden">
                        <img src={logoImg} alt="AuditForge Logo" className="h-5 w-5 object-contain" />
                    </div>
                    <div className="flex flex-col">
                        <span className="text-sm font-bold tracking-tight text-white leading-tight">
                            Audit<span className="text-ey-yellow">Forge</span>
                        </span>
                        <span className="text-[10px] font-medium text-dark-muted uppercase tracking-wider leading-tight">
                            {title}
                        </span>
                    </div>
                </div>

                {/* Navigation Links */}
                <div className="flex items-center gap-1.5 relative">
                    {navItems.map((item) => {
                        const Icon = item.icon;
                        const isActive =
                            item.path === '/'
                                ? location.pathname === '/'
                                : item.path === '/clients'
                                    ? location.pathname.startsWith('/clients') || location.pathname.startsWith('/missions')
                                    : location.pathname.startsWith(item.path);

                        return (
                            <Link
                                key={item.path}
                                to={item.path}
                                className={cn(
                                    'group relative flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium transition-colors z-10',
                                    isActive
                                        ? 'text-ey-yellow drop-shadow-[0_0_5px_rgba(255,230,0,0.5)]'
                                        : 'text-dark-secondary hover:text-white hover:bg-white/5',
                                )}
                            >
                                {isActive && (
                                    <motion.div
                                        layoutId="navbar-active-pill"
                                        className="absolute inset-0 rounded-full bg-ey-yellow/10 ring-1 ring-ey-yellow/20 shadow-[inset_0_0_12px_rgba(255,230,0,0.15)] -z-10"
                                        initial={false}
                                        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
                                    />
                                )}
                                <Icon className={cn('h-4 w-4 transition-transform duration-300 group-hover:scale-110', isActive ? 'text-ey-yellow drop-shadow-[0_0_5px_rgba(255,230,0,0.5)]' : '')} />
                                <span>{item.label}</span>
                                {isActive && (
                                    <motion.div
                                        layoutId="navbar-active-underline"
                                        className="absolute -bottom-1 left-1/2 h-0.5 w-6 -translate-x-1/2 rounded-full bg-ey-yellow shadow-[0_0_8px_rgba(255,230,0,0.8)]"
                                    />
                                )}
                            </Link>
                        );
                    })}
                </div>
            </nav>
        </div>
    );
}
