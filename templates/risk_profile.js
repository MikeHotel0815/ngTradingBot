// Risk Profile Management for Auto-Trading
// This script handles the 3-button risk profile selector (MODERATE/NORMAL/AGGRESSIVE)
// and displays dynamic confidence requirements based on market conditions

(function() {
    'use strict';
    
    const apiBase = window.location.protocol + '//' + window.location.hostname + ':9900';
    
    // Risk Profile Button Click Handler
    document.addEventListener('DOMContentLoaded', function() {
        const riskProfileBtns = document.querySelectorAll('.risk-profile-btn');
        
        riskProfileBtns.forEach(btn => {
            btn.addEventListener('click', async function() {
                const profile = this.dataset.profile;
                
                try {
                    const response = await fetch(apiBase + '/api/auto-trade/set-risk-profile', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ risk_profile: profile })
                    });
                    
                    const data = await response.json();
                    
                    if (response.ok) {
                        // Update button styles
                        riskProfileBtns.forEach(b => {
                            if (b.dataset.profile === profile) {
                                b.classList.add('active');
                                b.style.border = '2px solid #4CAF50';
                                b.style.background = '#1a4a1a';
                                b.style.color = '#4CAF50';
                                b.style.fontWeight = '600';
                            } else {
                                b.classList.remove('active');
                                b.style.border = '2px solid #555';
                                b.style.background = '#2a2a2a';
                                b.style.color = '#888';
                                b.style.fontWeight = 'normal';
                            }
                        });
                        
                        // Reload confidence requirements
                        if (typeof loadConfidenceRequirements === 'function') {
                            loadConfidenceRequirements();
                        }
                        
                        console.log('✅ Risk Profile set to:', profile);
                    } else {
                        console.error('❌ Failed to set risk profile:', data);
                        alert('Error: ' + data.message);
                    }
                } catch (error) {
                    console.error('❌ Error setting risk profile:', error);
                    alert('Error setting risk profile. Check console for details.');
                }
            });
        });
        
        // Refresh confidence requirements every 5 minutes
        if (typeof loadConfidenceRequirements === 'function') {
            setInterval(loadConfidenceRequirements, 300000); // 5 minutes
        }
    });
})();
