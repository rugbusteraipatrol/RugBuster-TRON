const RugBusterScanner = artifacts.require("RugBusterScanner");

module.exports = function (deployer) {
  deployer.deploy(RugBusterScanner);
};
