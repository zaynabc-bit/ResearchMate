import React from 'react';

export const RmLogo = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <path d="M11 7.5 C11 9.5, 10 10.5, 8 10.5 C10 10.5, 11 11.5, 11 13.5 C11 11.5, 12 10.5, 14 10.5 C12 10.5, 11 9.5, 11 7.5 Z" fill={color} stroke="none" />
  <circle cx="13.5" cy="13.5" r="1.2" fill={color} stroke="none" />
</svg>
);
