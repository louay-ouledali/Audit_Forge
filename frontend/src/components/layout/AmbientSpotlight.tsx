import React from 'react';

export default function AmbientSpotlight() {
  return (
    <div className="fixed inset-0 z-[-1] pointer-events-none overflow-hidden">
      <div 
        className="absolute w-[800px] h-[800px] rounded-full opacity-60 mix-blend-screen"
        style={{
          background: 'radial-gradient(circle at center, rgba(255, 230, 0, 0.05) 0%, transparent 60%)',
          top: '50%',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          animation: 'orbit 25s linear infinite'
        }}
      />
      <div 
        className="absolute w-[600px] h-[600px] rounded-full opacity-40 mix-blend-screen"
        style={{
          background: 'radial-gradient(circle at center, rgba(255, 230, 0, 0.04) 0%, transparent 65%)',
          top: '30%',
          left: '70%',
          animation: 'orbit 35s linear infinite reverse'
        }}
      />
      <style>{`
        @keyframes orbit {
          0% {
            transform: translate(-50%, -50%) rotate(0deg) translateX(150px) rotate(0deg);
          }
          100% {
            transform: translate(-50%, -50%) rotate(360deg) translateX(150px) rotate(-360deg);
          }
        }
      `}</style>
    </div>
  );
}
