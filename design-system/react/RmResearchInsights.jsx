import React from 'react';

export const RmResearchInsights = ({ size = 24, color = 'currentColor', ...props }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
  <circle cx="11" cy="11" r="7" />
  <line x1="16" y1="16" x2="21" y2="21" />
  <line x1="8" y1="13" x2="8" y2="11" strokeWidth="1.5" />
  <line x1="11" y1="13" x2="11" y2="8" strokeWidth="1.5" />
  <line x1="14" y1="13" x2="14" y2="10" strokeWidth="1.5" />
</svg>
);
