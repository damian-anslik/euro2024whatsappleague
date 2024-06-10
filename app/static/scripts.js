const getMatches = async () => {
  const response = await fetch("/matches", {
    headers: { "Cache-Control": "no-cache" },
  });
  const data = await response.json();
  return data;
};

const getUserBets = async () => {
  const response = await fetch("/bets", {
    headers: { "Cache-Control": "no-cache" },
  });
  const data = await response.json();
  return data;
};

const renderMatchDetails = (
  matchData,
  userMatchBet,
  isToday,
  numWildcardsRemaining
) => {
  if (!matchData.show) {
    return;
  }
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

  const createDividerElement = (homeTeamScore, awayTeamScore, matchStatus) => {
    if (homeTeamScore === null || awayTeamScore === null) {
      let divider = document.createElement("div");
      divider.innerText = "VS";
      divider.classList.add("fixture-scores");
      return divider;
    }
    let divider = document.createElement("div");
    divider.classList.add("fixture-scores");
    let scoreDiv = document.createElement("div");
    scoreDiv.classList.add("score");
    let homeTeamScoreElement = document.createElement("span");
    homeTeamScoreElement.innerText = homeTeamScore;
    let awayTeamScoreElement = document.createElement("span");
    awayTeamScoreElement.innerText = awayTeamScore;
    let dash = document.createElement("span");
    dash.innerText = " - ";
    scoreDiv.appendChild(homeTeamScoreElement);
    scoreDiv.appendChild(dash);
    scoreDiv.appendChild(awayTeamScoreElement);
    divider.appendChild(scoreDiv);
    // Add a note stating that score displayed is for regular time only
    if (matchStatus in { ET: 1, BT: 1, P: 1, AET: 1, PEN: 1 }) {
      let extraTime = document.createElement("span");
      extraTime.innerText = "End of regular time";
      extraTime.classList.add("score-note");
      divider.appendChild(extraTime);
    }
    return divider;
  };

  const createBetFormElement = (
    canUserPlaceBets,
    matchId,
    userBetData,
    matchStatus
  ) => {
    let form = document.createElement("form");
    form.action = "/bets";
    form.method = "POST";
    form.classList.add("bet-form");
    let errorContainer = document.createElement("div");
    errorContainer.classList.add("error-container");
    form.appendChild(errorContainer);
    let successContainer = document.createElement("div");
    successContainer.classList.add("success-container");
    form.appendChild(successContainer);
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
    // Wildcard toggle
    let wildcardToggle = document.createElement("input");
    wildcardToggle.id = "wildcard-toggle";
    wildcardToggle.type = "button";
    wildcardToggle.name = "use_wildcard";
    if (userBetData && userBetData.use_wildcard) {
      wildcardToggle.value = "Point Booster Enabled";
    } else {
      if (numWildcardsRemaining === 0) {
        wildcardToggle.value = "Point Booster Disabled (0 Remaining)";
        wildcardToggle.disabled = true;
      } else {
        wildcardToggle.value = `Point Booster Disabled (${numWildcardsRemaining} Remaining)`;
      }
    }
    wildcardToggle.onclick = () => {
      if (
        wildcardToggle.value ===
        `Point Booster Disabled (${numWildcardsRemaining} Remaining)`
      ) {
        wildcardToggle.value = "Point Booster Enabled (Submit to confirm)";
      } else if (
        wildcardToggle.value === "Point Booster Enabled (Submit to confirm)"
      ) {
        wildcardToggle.value = `Point Booster Disabled (${numWildcardsRemaining} Remaining)`;
      } else if (
        wildcardToggle.value === "Point Booster Disabled (Submit to confirm)"
      ) {
        wildcardToggle.value = `Point Booster Enabled`;
      } 
      else {
        wildcardToggle.value = `Point Booster Disabled (Submit to confirm)`;
      }
    };
    // Submit button
    let submit = document.createElement("button");
    submit.type = "submit";
    if (!canUserPlaceBets) {
      homeTeamBet.disabled = true;
      awayTeamBet.disabled = true;
      submit.disabled = true;
      wildcardToggle.disabled = true;
      if (matchStatus === "FT") {
        submit.innerText = "Match Ended";
      } else {
        submit.innerText = "Match In Progress";
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
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      errorContainer.style.display = "none";
      successContainer.style.display = "none";
      submit.innerText = "Submitting Prediction...";
      let formData = new FormData(form);
      formData.append(
        "use_wildcard",
        wildcardToggle.value.includes("Point Booster Enabled")
          ? 1
          : 0
      );
      let response = await fetch("/bets", {
        method: "POST",
        body: formData,
      });
      let responseData = await response.json();
      if (response.status !== 200) {
        errorContainer.style.display = "block";
        errorContainer.innerText = responseData.detail;
        submit.innerText = "Update Prediction";
        submit.disabled = false;
        return;
      }
      successContainer.innerText = "Prediction Submitted Successfully";
      successContainer.style.display = "block";
      submit.innerText = "Update Prediction";
      submit.disabled = false;
    });
    form.appendChild(homeTeamBet);
    form.appendChild(awayTeamBet);
    form.appendChild(fixtureId);
    form.appendChild(wildcardToggle);
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
  let leagueName = document.createElement("span");
  leagueName.classList.add("league-name");
  leagueName.innerText = matchData.league_name;
  if (matchData.league_name) {
    fixtureInfo.appendChild(leagueName);
  }
  let fixtureTime = document.createElement("span");
  fixtureTime.classList.add("fixture-time");
  let timestamp = new Date(matchData.timestamp).getTime();
  fixtureTime.innerText = {
    TBD: "Time To Be Decided",
    NS:
      (isToday ? "Today " : "Tomorrow ") +
      new Date(timestamp).toLocaleString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
      }),
    "1H": "First Half",
    HT: "Half Time",
    "2H": "Second Half",
    ET: "Extra Time",
    BT: "Break Time (Extra Time)",
    P: "Penalties",
    INT: "Match Interrupted",
    FT: "Full Time",
    AET: "Ended After Extra Time",
    PEN: "Ended After Penalties",
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
    matchData.away_team_goals,
    matchData.status
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
  // Show other users bets if bets field is available
  if (matchData.bets && matchData.bets.length > 0) {
    let revealUserPredictionsButton = document.createElement("button");
    revealUserPredictionsButton.innerText = "Show User Predictions";
    revealUserPredictionsButton.classList.add("show-bets-button");
    revealUserPredictionsButton.onclick = () => {
      let betsInfoTable = fixtureInfo.querySelector(".bets-info");
      if (betsInfoTable.style.display === "none") {
        betsInfoTable.style.display = "table";
        revealUserPredictionsButton.innerText = "Hide User Predictions";
      } else {
        betsInfoTable.style.display = "none";
        revealUserPredictionsButton.innerText = "Show User Predictions";
      }
    };
    fixtureInfo.appendChild(revealUserPredictionsButton);
    let betsInfoContainer = document.createElement("div");
    betsInfoContainer.classList.add("table-container");
    let betsInfoTable = document.createElement("table");
    betsInfoTable.classList.add("bets-info");
    let betsInfoTableHeader = document.createElement("tr");
    let usernameHeader = document.createElement("th");
    usernameHeader.innerText = "Name";
    let homeGoalsHeader = document.createElement("th");
    homeGoalsHeader.innerText = "Predicted Home Goals";
    let awayGoalsHeader = document.createElement("th");
    awayGoalsHeader.innerText = "Predicted Away Goals";
    let pointBoosterEnabledHeader = document.createElement("th");
    pointBoosterEnabledHeader.innerText = "Point Booster Enabled";
    betsInfoTableHeader.appendChild(usernameHeader);
    betsInfoTableHeader.appendChild(homeGoalsHeader);
    betsInfoTableHeader.appendChild(awayGoalsHeader);
    betsInfoTableHeader.appendChild(pointBoosterEnabledHeader);
    betsInfoTable.appendChild(betsInfoTableHeader);
    matchData.bets.forEach((bet) => {
      let betInfo = document.createElement("tr");
      let username = document.createElement("td");
      username.innerText = bet.user.name;
      let homeGoals = document.createElement("td");
      homeGoals.innerText = bet.predicted_home_goals;
      let awayGoals = document.createElement("td");
      awayGoals.innerText = bet.predicted_away_goals;
      let pointBoosterEnabled = document.createElement("td");
      pointBoosterEnabled.innerText = bet.use_wildcard ? "Yes" : "No";
      betInfo.appendChild(username);
      betInfo.appendChild(homeGoals);
      betInfo.appendChild(awayGoals);
      betInfo.appendChild(pointBoosterEnabled);
      betsInfoTable.appendChild(betInfo);
    });
    betsInfoTable.style.display = "none";
    betsInfoContainer.appendChild(betsInfoTable);
    fixtureInfo.appendChild(betsInfoContainer);
  }
  if (isToday) {
    let fixtures = document.querySelector(".todays-fixtures");
    fixtures.appendChild(fixtureInfo);
  } else {
    let fixtures = document.querySelector(".tomorrows-fixtures");
    fixtures.appendChild(fixtureInfo);
  }
};

document.addEventListener("DOMContentLoaded", async () => {
  let [matches, betsAndWildcardsRemaining] = await Promise.all([
    getMatches(),
    getUserBets(),
  ]);
  let todaysMatches = matches.today;
  let todaysShownMatches = todaysMatches.filter((match) => match.show);
  let tomorrowsMatches = matches.tomorrow;
  let tomorrowsShownMatches = tomorrowsMatches.filter((match) => match.show);
  let userBets = betsAndWildcardsRemaining.bets;
  let wildcardsRemaining = betsAndWildcardsRemaining.num_wildcards_remaining;
  if (todaysShownMatches.length === 0) {
    let noMatches = document.createElement("p");
    noMatches.classList.add("no-matches");
    noMatches.innerText = "No matches available at the moment";
    let fixtures = document.querySelector(".todays-fixtures");
    fixtures.appendChild(noMatches);
  } else {
    todaysShownMatches.forEach((match) => {
      let matchBets = userBets.filter((bet) => bet.match_id === match.id);
      renderMatchDetails(match, matchBets, true, wildcardsRemaining);
    });
  }
  if (tomorrowsShownMatches.length === 0) {
    let noMatches = document.createElement("p");
    noMatches.classList.add("no-matches");
    noMatches.innerText = "No matches available at the moment";
    let fixtures = document.querySelector(".tomorrows-fixtures");
    fixtures.appendChild(noMatches);
  } else {
    tomorrowsShownMatches.forEach((match) => {
      let matchBets = userBets.filter((bet) => bet.match_id === match.id);
      renderMatchDetails(match, matchBets, false, wildcardsRemaining);
    });
  }
  document.getElementsByClassName("todays-fixtures")[0].hidden = false;
  document.getElementsByClassName("tomorrows-fixtures")[0].hidden = false;
  document.getElementsByClassName("loading-indicator-container")[0].remove();
});
