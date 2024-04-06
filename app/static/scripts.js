const getMatches = async () => {
  const response = await fetch("/matches");
  const data = await response.json();
  return data;
};

const getUserBets = async () => {
  const response = await fetch("/bets");
  const data = await response.json();
  return data;
};

const renderMatchDetails = (matchData, userMatchBet, isToday) => {
  const createTeamDetailsElement = (teamName, teamLogoUrl) => {
    let teamInfo = document.createElement("div");
    teamInfo.classList.add("team-info");
    let teamLogo = document.createElement("img");
    teamLogo.src = teamLogoUrl;
    teamLogo.alt = teamName;
    let teamNameElement = document.createElement("p");
    teamNameElement.innerText = teamName;
    teamInfo.appendChild(teamLogo);
    teamInfo.appendChild(teamNameElement);
    return teamInfo;
  };

  const createDividerElement = (homeTeamScore, awayTeamScore) => {
    if (homeTeamScore === null || awayTeamScore === null) {
      let divider = document.createElement("div");
      divider.innerText = "VS";
      divider.classList.add("fixture-scores");
      return divider;
    }
    let divider = document.createElement("div");
    divider.classList.add("fixture-scores");
    let homeTeamScoreElement = document.createElement("span");
    homeTeamScoreElement.innerText = homeTeamScore;
    let awayTeamScoreElement = document.createElement("span");
    awayTeamScoreElement.innerText = awayTeamScore;
    let dash = document.createElement("span");
    dash.innerText = " - ";
    divider.appendChild(homeTeamScoreElement);
    divider.appendChild(dash);
    divider.appendChild(awayTeamScoreElement);
    return divider;
  };

  const createBetFormElement = (
    canUserPlaceBets,
    matchId,
    userBetData,
    matchStatus
  ) => {
    console.log(matchId, userBetData);
    let form = document.createElement("form");
    form.action = "/bets";
    form.method = "POST";
    form.classList.add("bet-form");
    let homeTeamBet = document.createElement("input");
    homeTeamBet.type = "number";
    homeTeamBet.name = "home_goals";
    homeTeamBet.min = 0;
    homeTeamBet.placeholder = `Your Prediction for ${matchData.home_team_name}`;
    homeTeamBet.required = true;
    let awayTeamBet = document.createElement("input");
    awayTeamBet.type = "number";
    awayTeamBet.name = "away_goals";
    awayTeamBet.placeholder = `Your Prediction for ${matchData.away_team_name}`;
    awayTeamBet.min = 0;
    awayTeamBet.required = true;
    let submit = document.createElement("button");
    submit.type = "submit";
    if (!canUserPlaceBets) {
      homeTeamBet.disabled = true;
      awayTeamBet.disabled = true;
      submit.disabled = true;
      if (matchStatus === "FT") {
        submit.innerText = "Match Ended";
      } else {
        submit.innerText = "Match Started - Cannot Update Prediction Anymore";
      }
      submit.classList.add("disabled");
    } else if (userBetData) {
      submit.innerText = "Update Prediction";
    } else {
      submit.innerText = "Predict Score";
    }
    if (userBetData) {
      homeTeamBet.value = userBetData.predicted_home_goals;
      awayTeamBet.value = userBetData.predicted_away_goals;
    }
    let fixtureId = document.createElement("input");
    fixtureId.type = "hidden";
    fixtureId.name = "fixture_id";
    fixtureId.value = matchId;
    form.appendChild(homeTeamBet);
    form.appendChild(awayTeamBet);
    form.appendChild(fixtureId);
    form.appendChild(submit);
    return form;
  };

  let fixtureInfo = document.createElement("div");
  fixtureInfo.classList.add("fixture-info");
  let isOngoingMatch = matchData.status in { "1H": 1, "2H": 1, ET: 1, HT: 1 };
  if (!matchData.can_users_place_bets && !isOngoingMatch) {
    fixtureInfo.classList.add("disabled");
  } else if (isOngoingMatch) {
    fixtureInfo.classList.add("ongoing");
  }
  let fixtureTime = document.createElement("span");
  fixtureTime.classList.add("fixture-time");
  let timestamp = new Date(matchData.timestamp).getTime();
  console.log(isOngoingMatch, matchData.status);
  fixtureTime.innerText = {
    NS: isToday
      ? "Today "
      : "Tomorrow " +
        new Date(timestamp).toLocaleString("en-GB", {
          hour: "2-digit",
          minute: "2-digit",
        }),
    "1H": "First Half",
    HT: "Half Time",
    "2H": "Second Half",
    ET: "Extra Time",
    FT: "Full Time",
  }[matchData.status];
  // Render teams
  let teamsInfo = document.createElement("div");
  teamsInfo.classList.add("teams-info");
  // Show information about the teams
  let homeTeamInfo = createTeamDetailsElement(
    matchData.home_team_name,
    matchData.home_team_logo
  );
  let awayTeamInfo = createTeamDetailsElement(
    matchData.away_team_name,
    matchData.away_team_logo
  );
  let teamDivider = createDividerElement(
    matchData.home_team_goals,
    matchData.away_team_goals
  );
  teamsInfo.appendChild(homeTeamInfo);
  teamsInfo.appendChild(teamDivider);
  teamsInfo.appendChild(awayTeamInfo);
  fixtureInfo.appendChild(fixtureTime);
  fixtureInfo.appendChild(teamsInfo);
  // Bet form
  let betForm = createBetFormElement(
    matchData.can_users_place_bets,
    matchData.id,
    userMatchBet[0],
    matchData.status
  );
  fixtureInfo.appendChild(betForm);
  if (isToday) {
    let fixtures = document.querySelector(".todays-fixtures");
    fixtures.appendChild(fixtureInfo);
  } else {
    let fixtures = document.querySelector(".tomorrows-fixtures");
    fixtures.appendChild(fixtureInfo);
  }
};

document.addEventListener("DOMContentLoaded", async () => {
  let matches = await getMatches();
  let userBets = await getUserBets();
  let todaysMatches = matches.today;
  let tomorrowsMatches = matches.tomorrow;
  if (todaysMatches.length === 0) {
    let noMatches = document.createElement("p");
    noMatches.classList.add("no-matches");
    noMatches.innerText = "No matches available at the moment";
    let fixtures = document.querySelector(".todays-fixtures");
    fixtures.appendChild(noMatches);
  } else {
    todaysMatches.forEach((match) => {
      let matchBets = userBets.filter((bet) => bet.match_id === match.id);
      renderMatchDetails(match, matchBets, true);
    });
  }
  if (tomorrowsMatches.length === 0) {
    let noMatches = document.createElement("p");
    noMatches.classList.add("no-matches");
    noMatches.innerText = "No matches available at the moment";
    let fixtures = document.querySelector(".tomorrows-fixtures");
    fixtures.appendChild(noMatches);
  } else {
    tomorrowsMatches.forEach((match) => {
      let matchBets = userBets.filter((bet) => bet.match_id === match.id);
      renderMatchDetails(match, matchBets, false);
    });
  }
  document.getElementsByClassName("todays-fixtures")[0].hidden = false;
  document.getElementsByClassName("tomorrows-fixtures")[0].hidden = false;
  document.getElementsByClassName("loading-indicator-container")[0].remove();
});
