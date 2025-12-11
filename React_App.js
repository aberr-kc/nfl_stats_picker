import React, { useState, useEffect } from 'react';
import axios from 'axios';
import './App.css';

const API_BASE = 'http://localhost:8000';

function App() {
  const [players, setPlayers] = useState([]);
  const [selectedPlayer, setSelectedPlayer] = useState('');
  const [selectedYear, setSelectedYear] = useState('2025');
  const [weeklyStats, setWeeklyStats] = useState([]);
  const [seasonAvg, setSeasonAvg] = useState({});
  const [recentAvg, setRecentAvg] = useState({});
  const [recent3Avg, setRecent3Avg] = useState({});
  const [odds, setOdds] = useState([]);
  const [picks, setPicks] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchPlayers();
  }, []);

  const fetchPlayers = async () => {
    try {
      const response = await axios.get(`${API_BASE}/players`);
      setPlayers(response.data);
    } catch (error) {
      console.error('Error fetching players:', error);
    }
  };

  const fetchPlayerData = async (player, year) => {
    if (!player) return;
    
    setLoading(true);
    try {
      const [weeklyRes, seasonRes, recentRes, recent3Res, oddsRes] = await Promise.all([
        axios.get(`${API_BASE}/stats/year/${year}/player/${encodeURIComponent(player)}`),
        axios.get(`${API_BASE}/stats/year/${year}/player/${encodeURIComponent(player)}/season_avg`),
        axios.get(`${API_BASE}/stats/recent_average/${year}/player/${encodeURIComponent(player)}`),
        axios.get(`${API_BASE}/stats/recent_3_average/${year}/player/${encodeURIComponent(player)}`),
        axios.get(`${API_BASE}/odds/player/${encodeURIComponent(player)}`)
      ]);

      setWeeklyStats(weeklyRes.data);
      setSeasonAvg(seasonRes.data);
      setRecentAvg(recentRes.data);
      setRecent3Avg(recent3Res.data);
      setOdds(oddsRes.data);
    } catch (error) {
      console.error('Error fetching player data:', error);
    }
    setLoading(false);
  };

  const generatePicks = async () => {
    setLoading(true);
    try {
      const response = await axios.get(`${API_BASE}/generate-picks`);
      if (response.data.success) {
        setPicks(response.data.players || []);
      }
    } catch (error) {
      console.error('Error generating picks:', error);
    }
    setLoading(false);
  };

  const renderStatsTable = (stats) => {
    if (!stats || stats.length === 0) return <p>No data available</p>;
    
    const keys = Object.keys(stats[0]).filter(key => 
      !['player_id', 'season', 'player_display_name'].includes(key)
    );

    return (
      <table className="stats-table">
        <thead>
          <tr>
            {keys.map(key => <th key={key}>{key}</th>)}
          </tr>
        </thead>
        <tbody>
          {stats.map((stat, idx) => (
            <tr key={idx}>
              {keys.map(key => <td key={key}>{stat[key] || '-'}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const renderAvgTable = (avgData) => {
    if (!avgData || Object.keys(avgData).length === 0) return <p>No data available</p>;
    
    return (
      <table className="stats-table">
        <thead>
          <tr><th>Stat</th><th>Average</th></tr>
        </thead>
        <tbody>
          {Object.entries(avgData).map(([key, value]) => (
            <tr key={key}>
              <td>{key}</td>
              <td>{typeof value === 'number' ? value.toFixed(2) : value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  };

  const renderOdds = () => {
    if (!odds || odds.length === 0) return <p>No odds available</p>;
    
    const groupedOdds = odds.reduce((acc, odd) => {
      const market = odd.market || 'unknown';
      if (!acc[market]) acc[market] = [];
      acc[market].push(odd);
      return acc;
    }, {});

    return (
      <div className="odds-container">
        {Object.entries(groupedOdds).map(([market, marketOdds]) => (
          <div key={market} className="market-section">
            <h4>{market.replace(/_/g, ' ')}</h4>
            <div className="odds-chips">
              {marketOdds.map((odd, idx) => (
                <div key={idx} className="odd-chip">
                  <div className="bookmaker">{odd.bookmaker}</div>
                  <div className="line-price">{odd.line} ({odd.price})</div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className="App">
      <header className="app-header">
        <h1>🏈 NFL STAT PICKS</h1>
        <div className="controls">
          <select value={selectedYear} onChange={(e) => setSelectedYear(e.target.value)}>
            <option value="2025">2025</option>
            <option value="2024">2024</option>
            <option value="2023">2023</option>
          </select>
          
          <input
            type="text"
            list="players"
            placeholder="Type player name..."
            value={selectedPlayer}
            onChange={(e) => {
              setSelectedPlayer(e.target.value);
              fetchPlayerData(e.target.value, selectedYear);
            }}
          />
          <datalist id="players">
            {players.map(player => <option key={player} value={player} />)}
          </datalist>
          
          <button onClick={generatePicks} disabled={loading}>
            {loading ? 'Generating...' : 'Generate Picks'}
          </button>
        </div>
      </header>

      <main className="main-content">
        <div className="stats-grid">
          <section className="stats-section">
            <h2>📊 Weekly Performance</h2>
            {loading ? <p>Loading...</p> : renderStatsTable(weeklyStats)}
          </section>

          <section className="stats-section">
            <h2>📈 Season Averages</h2>
            {loading ? <p>Loading...</p> : renderAvgTable(seasonAvg)}
          </section>

          <section className="stats-section">
            <h2>🔥 Recent Form (5)</h2>
            {loading ? <p>Loading...</p> : renderAvgTable(recentAvg)}
          </section>

          <section className="stats-section">
            <h2>🔥 Recent Form (3)</h2>
            {loading ? <p>Loading...</p> : renderAvgTable(recent3Avg)}
          </section>
        </div>

        <section className="odds-section">
          <h2>💰 Betting Lines</h2>
          {loading ? <p>Loading...</p> : renderOdds()}
        </section>

        {picks.length > 0 && (
          <section className="picks-section">
            <h2>🎯 Generated Picks ({picks.length})</h2>
            <div className="picks-container">
              {picks.map((pick, idx) => (
                <div key={idx} className="pick-card">
                  <h3>{pick.player}</h3>
                  <p>{pick.matchup}</p>
                  {pick.stats?.map((stat, statIdx) => (
                    <div key={statIdx} className="stat-line">
                      <strong>{stat.stat}:</strong> {stat.player_value} vs {stat.line}
                      {stat.probabilityOver && (
                        <span className="probability">
                          {stat.probabilityOver}% Over | {stat.probabilityUnder}% Under
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}

export default App;